"""pygls language server that runs PythonTA through the runner subprocess."""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import tokenize
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from lsprotocol import types
from pygls import uris
from pygls.lsp.server import LanguageServer

from . import __version__
from .diagnostics import config_diagnostic, failure_diagnostic, to_diagnostic
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


def is_package_module(path: str) -> bool:
    """Whether the file is part of a package, and so cannot be checked from a copy.

    A copy in a temp directory is not inside the package, so relative imports
    resolve to nothing and PythonTA reports an import error that is not real.
    """
    return os.path.isfile(os.path.join(os.path.dirname(path), "__init__.py"))


_COOKIE_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*(?P<name>[-_.a-zA-Z0-9]+)")


def normalise_coding_cookie(source: str) -> str:
    """Point a PEP 263 cookie at utf-8, because the staged copy is written as utf-8.

    Left alone, the tokenizer decodes those utf-8 bytes as the declared encoding,
    so every non-ASCII character counts twice and columns, line lengths and the
    messages that follow from them are all wrong. Only the encoding name changes,
    so the line count does not move.
    """
    lines = source.split("\n")
    for index in range(min(2, len(lines))):
        match = _COOKIE_RE.match(lines[index])
        if match:
            if match.group("name").lower().replace("_", "-") not in ("utf-8", "utf8"):
                start, end = match.span("name")
                lines[index] = lines[index][:start] + "utf-8" + lines[index][end:]
            return "\n".join(lines)
        if lines[index].strip() and not lines[index].lstrip().startswith("#"):
            break
    return source


# The order python_ta.config.find_local_config tries, and the only names it knows.
_LOCAL_CONFIG_NAMES = (".pylintrc", "pylintrc", "pyproject.toml")


def find_local_config(directory: str) -> str | None:
    """The config/ file PythonTA would load from beside a file in `directory`.

    A copy of python_ta.config.find_local_config: calling the real one would pull
    pylint and astroid into a process that lives for the whole session, and the
    server deliberately keeps that in the runner subprocess.
    """
    for name in _LOCAL_CONFIG_NAMES:
        candidate = os.path.join(directory, "config", name)
        if os.path.exists(candidate):
            return candidate
    return None


def matches_disk(path: str, source: str) -> bool:
    """Whether the buffer is what a checker reading the file would see."""
    try:
        with open(path, "rb") as handle:
            encoding, _ = tokenize.detect_encoding(handle.readline)
        with open(path, "r", encoding=encoding, newline="") as handle:
            return handle.read() == source
    except (OSError, UnicodeDecodeError, SyntaxError, LookupError):
        return False


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

    def stop_checks(self) -> None:
        """Release everything holding the process open.

        The check pool's threads are not daemons, so the interpreter joins them on
        the way out; one parked on a 60-second subprocess wait keeps the whole
        server alive after the editor has gone. Killing the subprocesses first is
        what lets those threads return.
        """
        self.scheduler.cancel_all()
        self._checks.shutdown(wait=False, cancel_futures=True)

    def begin_stop_checks(self) -> threading.Thread:
        """Start stop_checks off the event loop.

        Killing a tree waits on taskkill, and the loop that would be waiting also
        reads stdin. The thread is not a daemon, so the interpreter joins it and
        the tree is dead before the process is.
        """
        thread = threading.Thread(target=self.stop_checks, name="pyta-stop-checks")
        thread.start()
        return thread

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
        source_dir = os.path.dirname(path)
        try:
            source: str | None = doc.source
            lines: list[str] | None = doc.lines
        except (OSError, UnicodeDecodeError) as exc:
            source, lines = None, None
            self.log_to_client(
                f"Could not read {path} for positions: {exc}", types.MessageType.Warning
            )
        # Staging is what lets a dirty buffer or a non-UTF-8 file be checked at all,
        # but a package module has to stay where it is.
        stage = source is not None and not is_package_module(path)
        if source is not None and not stage and not matches_disk(path, source):
            # Nothing correct is available: the buffer cannot be checked where it is,
            # and the file on disk is not what the student is looking at.
            reason = "unsaved changes in a package module cannot be checked; save the file first"
            self.log_to_client(f"{path}: {reason}", types.MessageType.Warning)
            diagnostics = [failure_diagnostic(reason)]
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
            )
            self.notify_status(uri, "done", len(diagnostics))
            return
        staging = tempfile.mkdtemp(prefix="pyta-lsp-") if stage else None
        try:
            target = path
            if staging is not None and source is not None:
                # PythonTA reads the path it is given as UTF-8, and the editor buffer
                # can differ from disk, so check a UTF-8 copy of what the user sees.
                target = os.path.join(staging, os.path.basename(path))
                with open(target, "w", encoding="utf-8", newline="") as handle:
                    handle.write(normalise_coding_cookie(source))
                # PythonTA loads config/.pylintrc from beside the file it is given,
                # so without this the copy is checked against a different config
                # than the student's own run uses.
                local_config = find_local_config(source_dir)
                if local_config:
                    os.mkdir(os.path.join(staging, "config"))
                    shutil.copyfile(
                        local_config,
                        os.path.join(staging, "config", os.path.basename(local_config)),
                    )
            argv = [sys.executable, "-m", "pyta_lsp.runner", target, "--source-dir", source_dir]
            if self.settings.config_path:
                argv += ["--config", self.settings.config_path]
                root = select_workspace_root(self.workspace_folders, path)
                if root:
                    argv += ["--workspace-root", root]
            # On 3.10 PYTHONSAFEPATH does nothing, so sys.path[0] is whatever the
            # runner is spawned in. The staging directory holds only the copy; for
            # a package module that has to stay put it is the package directory.
            result = self.scheduler.run(uri, argv, os.path.dirname(target))
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
        if result is None:
            return
        generation = result.pop(GENERATION_KEY)
        if result.get("ok"):
            diagnostics = [to_diagnostic(m, lines) for m in result.get("messages", [])]
            # The config file's own messages: not the student's to fix, but not silent either.
            diagnostics.extend(config_diagnostic(m) for m in result.get("elsewhere", []))
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
        # Publish first: the cancel can wait on taskkill, and a reopen checked in
        # the meantime must not have its results wiped afterwards.
        self.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))
        self.scheduler.cancel(uri)


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


@server.feature(types.SHUTDOWN)
def on_shutdown(ls: PytaLanguageServer, params: Any = None) -> None:
    # Not @server.thread(): pygls resumes its own shutdown generator on the worker
    # thread, where the request id is not in context, and it then cancels the very
    # request it is answering. The kill goes to a thread of this handler's own,
    # and __main__ calls stop_checks again once start_io returns.
    ls.begin_stop_checks()


# Clearing cancels the document's check, and that kill waits on taskkill, which
# must not happen on the loop that also reads stdin.
@server.thread()
@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: PytaLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    ls.clear(params.text_document.uri)


@server.command(CHECK_COMMAND)
def command_check(ls: PytaLanguageServer, uri: str) -> None:
    ls.schedule_check(uri)


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
