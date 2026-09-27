"""pygls language server that runs PythonTA through the runner subprocess."""
from __future__ import annotations

import contextlib
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
from .diagnostics import (
    config_diagnostic,
    config_warning_diagnostic,
    failure_diagnostic,
    split_lines,
    to_diagnostic,
)
from .paths import module_launcher
from .scheduler import GENERATION_KEY, CheckScheduler

log = logging.getLogger("pyta_lsp")
STATUS_NOTIFICATION = "pyta/status"
CHECK_COMMAND = "pyta.check"
CONFIG_SECTION = "pythonta"


@dataclass
class Settings:
    """The client settings we honour.

    Attributes:
        run_on_save: check a file every time it gets saved.
        run_on_open: check a file every time it gets opened.
        config_path: config file from settings, used when the file asks for nothing.
    """

    run_on_save: bool = True
    run_on_open: bool = True
    config_path: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        """Read settings out of whatever the client sent, flat or nested, else defaults."""
        if not isinstance(data, dict):
            return cls()
        section = data.get(CONFIG_SECTION) if isinstance(data.get(CONFIG_SECTION), dict) else data
        return cls(
            run_on_save=bool(section.get("runOnSave", True)),
            run_on_open=bool(section.get("runOnOpen", True)),
            config_path=str(section.get("configPath") or ""),
        )


def select_workspace_root(folders: list[str], path: str) -> str | None:
    """The workspace folder holding this file, so a relative configPath resolves against it.

    A multi root workspace can hold one folder per course, each with a config of its
    own, so resolving every file against the first folder loads the wrong one.

    Args:
        folders: the open workspace folders.
        path: the file being checked.

    Returns:
        The deepest folder the file sits in, or the first folder when it sits in none.
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
    """Checks if the file is part of a package, which means it cant be checked from a copy.

    A copy in a temp directory is not inside the package, so relative imports
    resolve to nothing and PythonTA reports an import error that is not real.
    """
    return os.path.isfile(os.path.join(os.path.dirname(path), "__init__.py"))


_COOKIE_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*(?P<name>[-_.a-zA-Z0-9]+)")


def normalise_coding_cookie(source: str) -> str:
    """Point a PEP 263 cookie at utf-8, because we write the staged copy as utf-8.

    Left alone, the tokenizer decodes those utf-8 bytes as the declared encoding, so
    every non-ASCII character counts twice and columns, line lengths and the messages
    that come out of them are all wrong. Only the encoding name changes, so no line
    moves and no separator changes.

    The split has to match the tokenizer. On "\\n" alone a CR only buffer is one line
    and the pattern would then find a "coding=" anywhere in the file. A buffer behind
    a BOM is left alone, because a non-utf-8 cookie there is already a SyntaxError
    before this runs, same as before.
    """
    lines = split_lines(source)
    for index in range(min(2, len(lines))):
        line = lines[index]
        content = line.rstrip("\r\n")
        ending = line[len(content):]
        match = _COOKIE_RE.match(content)
        if match:
            if match.group("name").lower().replace("_", "-") not in ("utf-8", "utf8"):
                start, end = match.span("name")
                lines[index] = content[:start] + "utf-8" + content[end:] + ending
            return "".join(lines)
        if content.strip() and not content.lstrip().startswith("#"):
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


def _one_eol(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def matches_disk(path: str, source: str) -> bool:
    """Checks if the buffer matches what a file reader would see.

    We normalise line endings on both sides, because the editor shows a document
    with one EOL whatever the file holds, so a saved file with mixed endings would
    otherwise look like an unsaved buffer.
    """
    try:
        with open(path, "rb") as handle:
            encoding, _ = tokenize.detect_encoding(handle.readline)
        with open(path, "r", encoding=encoding, newline="") as handle:
            return _one_eol(handle.read()) == _one_eol(source)
    except (OSError, UnicodeDecodeError, SyntaxError, LookupError):
        return False


class PytaLanguageServer(LanguageServer):
    """The language server, running one PythonTA check per open document.

    Attributes:
        settings: the client settings we honour.
        scheduler: runs the runner subprocesses and decides which result is current.
        workspace_folders: the open folders, used to resolve a relative configPath.
        _checks: the thread pool checks run on, kept away from the pygls pool.
    """

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

        Threads in the check pool arent daemons, so the interpreter joins them on the
        way out, and one parked on a 60 second subprocess wait keeps the whole server
        alive after the editor is gone. Killing the subprocesses first is what lets
        those threads return.
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
        """Check one document and publish whatever comes back, failure included."""
        path = uris.to_fs_path(uri)
        if not path:
            return
        doc = self.workspace.get_text_document(uri)
        if doc.language_id not in (None, "python"):
            return
        self.notify_status(uri, "checking")
        # Claimed before anything that can fail, so a failure can tell whether it is
        # still the newest word on this document.
        generation = self.scheduler.reserve(uri)
        try:
            self._check(uri, path, doc, generation)
        except Exception as exc:
            # Staging and the spawn can both fail. Returning from one of them left
            # no diagnostics and no terminal status, so the status bar spun for the
            # rest of the session.
            log.exception("PythonTA check failed for %s", uri)
            reason = str(exc) or type(exc).__name__
            self.log_to_client(f"PythonTA could not check {path}: {reason}", types.MessageType.Error)
            self.fail(uri, generation, reason)

    def fail(self, uri: str, generation: int, reason: str) -> None:
        """Report a check that produced nothing, unless a newer one took the file.

        Publishing without the guard let an early failure like mkdtemp or the staged
        write wipe the diagnostics of a check already running on the same document,
        and flip its status bar to done while it was still going. The publish happens
        inside the same lock, because a did_close between the decision and the publish
        leaves the failure on a document that is no longer open.

        Args:
            uri: the document the failure belongs to.
            generation: the version ID this check reserved.
            reason: what went wrong, shown to the user as the diagnostic.
        """

        def publish() -> None:
            self.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[failure_diagnostic(reason)])
            )
            self.notify_status(uri, "done", 1)

        self.scheduler.fail(uri, generation, publish)

    def _check(self, uri: str, path: str, doc: Any, generation: int) -> None:
        """Stage the buffer when we can, spawn the runner, then publish the result.

        Args:
            uri: the document being checked.
            path: the file on disk behind that document.
            doc: the open document, read once for its text.
            generation: the version ID reserved by check().
        """
        source_dir = os.path.dirname(path)
        try:
            # One read only, because doc.source can hit the disk and a didChange
            # between two reads would map these messages onto a different text.
            source: str | None = doc.source
            lines: list[str] | None = split_lines(source)
        except (OSError, UnicodeDecodeError) as exc:
            source, lines = None, None
            self.log_to_client(
                f"Could not read {path} for positions: {exc}", types.MessageType.Warning
            )
        # Staging help test unsaved changes or weird file encodings but actual
        # package modules cant be moved around.
        stage = source is not None and not is_package_module(path)
        if source is not None and not stage and not matches_disk(path, source):
            # Still unsolved: cant test the open editor buffer as it is, and the file
            # saved on disk doesnt match what the student sees
            reason = "unsaved changes in a package module cannot be checked; save the file first"
            self.log_to_client(f"{path}: {reason}", types.MessageType.Warning)
            self.fail(uri, generation, reason)
            return
        staging = tempfile.mkdtemp(prefix="pyta-lsp-") if stage else None
        try:
            target = path
            if staging is not None and source is not None:
                # PythonTA assumes files are UTF-8, but the open editor might not match
                # it, so we test a UTF-8 copy of what the user is looking at. The copy
                # goes one level below the spawn directory, because that directory is
                # sys.path[0] on 3.10 and a copy named random.py or string.py sitting
                # there gets imported before anything can strip it.
                staged_dir = os.path.join(staging, "staged")
                os.mkdir(staged_dir)
                target = os.path.join(staged_dir, os.path.basename(path))
                with open(target, "w", encoding="utf-8", newline="") as handle:
                    handle.write(normalise_coding_cookie(source))
                # PythonTA loads config/.pylintrc from beside the file it is given, so
                # without this the copy is checked against a different config than the
                # one a student run would use.
                local_config = find_local_config(source_dir)
                if local_config:
                    staged_config = os.path.join(
                        staged_dir, "config", os.path.basename(local_config)
                    )
                    try:
                        os.mkdir(os.path.join(staged_dir, "config"))
                        shutil.copyfile(local_config, staged_config)
                    except OSError as exc:
                        # copyfile writes before it fails, and find_local_config
                        # would then hand python_ta a truncated config, which is a
                        # worse answer than the defaults.
                        with contextlib.suppress(OSError):
                            os.remove(staged_config)
                        # Checking against the wrong config is bad but not checking
                        # at all is worse, and raising here meant exactly that.
                        self.log_to_client(
                            f"Could not copy {local_config} beside the staged file: {exc}; "
                            "checking without it",
                            types.MessageType.Warning,
                        )
            # Not -m: for a package module the runner starts in the package
            # directory, and -m would put it on sys.path before runpy imports
            # anything, so a student types.py there would run on 3.10.
            argv = [sys.executable, *module_launcher("pyta_lsp.runner"), target, "--source-dir", source_dir]
            if self.settings.config_path:
                argv += ["--config", self.settings.config_path]
                root = select_workspace_root(self.workspace_folders, path)
                if root:
                    argv += ["--workspace-root", root]
            # The launcher keeps the spawn directory off sys.path, and the staging
            # root holds one subdirectory and nothing importable anyway. A package
            # module has to stay put, so its runner starts in the package directory,
            # where mypy can shorten the paths it reports.
            spawn_dir = staging if staging is not None else os.path.dirname(target)
            result = self.scheduler.run(uri, argv, spawn_dir, generation)
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
        if result is None:
            return
        generation = result.pop(GENERATION_KEY)
        if result.get("ok"):
            diagnostics = [to_diagnostic(m, lines) for m in result.get("messages", [])]
            # Config file message is not for the users to fix but it will still display.
            diagnostics.extend(config_diagnostic(m) for m in result.get("elsewhere", []))
            # Every warning the runner returns comes from reading the check_all call
            # in the file, and each one means this check used a different config than
            # that call asks for.
            for warning in result.get("warnings", []):
                self.log_to_client(f"{path}: {warning}", types.MessageType.Warning)
                diagnostics.append(config_warning_diagnostic(warning))
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
        """Drop the diagnostics for a document and stop any check still on it."""
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
    # Not @server.thread(), because pygls resumes its own shutdown generator on the
    # worker thread where the request id is not in context, and it then cancels the
    # very request it is answering. The kill goes to a thread this handler owns, and
    # __main__ calls stop_checks again once start_io returns.
    ls.begin_stop_checks()


# Clearing cancels the check on that document, and the kill waits on taskkill,
# which must not happen on the loop that also reads stdin.
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
