"""pygls language server that runs PythonTA through the runner subprocess."""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from lsprotocol import types
from pygls import uris
from pygls.lsp.server import LanguageServer

from . import __version__
from .diagnostics import failure_diagnostic, to_diagnostic
from .scheduler import GENERATION_KEY, CheckScheduler

log = logging.getLogger("pyta_lsp")
STATUS_NOTIFICATION = "pyta/status"
CHECK_COMMAND = "pyta.check"
CONFIG_SECTION = "pythonta"


@dataclass
class Settings:
    run_on_save: bool = True
    run_on_open: bool = True
    config_path: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        section = data.get(CONFIG_SECTION) if isinstance(data.get(CONFIG_SECTION), dict) else data
        return cls(
            run_on_save=bool(section.get("runOnSave", True)),
            run_on_open=bool(section.get("runOnOpen", True)),
            config_path=str(section.get("configPath") or ""),
        )


def select_workspace_root(folders: list[str], path: str) -> str | None:
    """The folder holding the file, so a relative configPath resolves against it.

    A multi-root workspace can hold one folder per course, each with its own
    config; resolving every file against the first folder loads the wrong one.
    """
    if not folders:
        return None
    target = os.path.normcase(os.path.abspath(path))
    best: str | None = None
    best_len = -1
    for folder in folders:
        prefix = os.path.normcase(os.path.abspath(folder))
        if target == prefix or target.startswith(prefix + os.sep):
            if len(prefix) > best_len:
                best, best_len = folder, len(prefix)
    return best if best is not None else folders[0]


class PytaLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__(name="pyta-lsp", version=__version__, max_workers=12)
        self.settings = Settings()
        self.scheduler = CheckScheduler()
        self.workspace_folders: list[str] = []
        # Checks get their own pool. The pygls pool also serves the stdin reader,
        # so a burst of opens running there can stall every later message until a
        # subprocess finishes. Queued work waits here instead.
        self._checks = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pyta-check")

    def schedule_check(self, uri: str) -> None:
        self._checks.submit(self._run_check, uri)

    def _run_check(self, uri: str) -> None:
        try:
            self.check(uri)
        except Exception:  # a worker thread swallows exceptions silently otherwise
            log.exception("PythonTA check failed for %s", uri)

    def notify_status(self, uri: str, state: str, count: int | None = None) -> None:
        self.protocol.notify(STATUS_NOTIFICATION, {"uri": uri, "state": state, "count": count})

    def log_to_client(self, message: str, level: types.MessageType = types.MessageType.Log) -> None:
        self.window_log_message(types.LogMessageParams(type=level, message=message))

    def check(self, uri: str) -> None:
        path = uris.to_fs_path(uri)
        if not path:
            return
        doc = self.workspace.get_text_document(uri)
        if doc.language_id not in (None, "python"):
            return
        self.notify_status(uri, "checking")
        argv = [sys.executable, "-m", "pyta_lsp.runner", path]
        if self.settings.config_path:
            argv += ["--config", self.settings.config_path]
            root = select_workspace_root(self.workspace_folders, path)
            if root:
                argv += ["--workspace-root", root]
        result = self.scheduler.run(uri, argv, os.path.dirname(path))
        if result is None:
            return
        generation = result.pop(GENERATION_KEY)
        if result.get("ok"):
            try:
                lines = doc.lines
            except (OSError, UnicodeDecodeError) as exc:
                lines = None
                self.log_to_client(
                    f"Could not read {path} for positions: {exc}", types.MessageType.Warning
                )
            diagnostics = [to_diagnostic(m, lines) for m in result.get("messages", [])]
            for warning in result.get("warnings", []):
                self.log_to_client(f"{path}: {warning}", types.MessageType.Warning)
        else:
            reason = str(result.get("error") or "unknown error")
            diagnostics = [failure_diagnostic(reason)]
            detail = "\n".join(s for s in (result.get("traceback"), result.get("log")) if s)
            self.log_to_client(f"PythonTA failed on {path}: {reason}\n{detail}", types.MessageType.Error)
        def publish() -> None:
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
            )
            self.notify_status(uri, "done", len(diagnostics))

        self.scheduler.guard(uri, generation, publish)

    def clear(self, uri: str) -> None:
        self.scheduler.cancel(uri)
        self.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


server = PytaLanguageServer()


@server.feature(types.INITIALIZE)
def on_initialize(ls: PytaLanguageServer, params: types.InitializeParams) -> None:
    ls.settings = Settings.from_dict(params.initialization_options)
    folders = params.workspace_folders or []
    roots = [uris.to_fs_path(folder.uri) for folder in folders]
    if not roots and params.root_uri:
        roots = [uris.to_fs_path(params.root_uri)]
    ls.workspace_folders = [root for root in roots if root]


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: PytaLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    if ls.settings.run_on_open:
        ls.schedule_check(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: PytaLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    if ls.settings.run_on_save:
        ls.schedule_check(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: PytaLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    ls.clear(params.text_document.uri)


@server.thread()
@server.command(CHECK_COMMAND)
def command_check(ls: PytaLanguageServer, uri: str) -> None:
    ls.check(uri)


@server.thread()
@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
def did_change_configuration(ls: PytaLanguageServer, params: types.DidChangeConfigurationParams) -> None:
    settings: Any = None
    try:
        items = ls.workspace_configuration(
            types.ConfigurationParams(items=[types.ConfigurationItem(section=CONFIG_SECTION)])
        ).result(5)
        if items and isinstance(items[0], dict):
            settings = items[0]
    except Exception as exc:  # clients without workspace/configuration support
        log.warning("workspace/configuration unavailable: %s", exc)
    if settings is None and isinstance(params.settings, dict):
        settings = params.settings
    if settings is not None:
        ls.settings = Settings.from_dict(settings)
