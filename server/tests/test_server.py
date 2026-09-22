import json
import sys
import time
from collections.abc import AsyncGenerator

import pytest
import pytest_lsp
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import FIXTURES


@pytest_lsp.fixture(config=ClientServerConfig(server_command=[sys.executable, "-m", "pyta_lsp"]))
async def client(lsp_client: LanguageClient) -> AsyncGenerator[None, None]:
    result = await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=FIXTURES.as_uri(),
            initialization_options={"runOnOpen": True, "runOnSave": True, "configPath": ""},
        )
    )
    lsp_client.server_capabilities = result.capabilities  # type: ignore[attr-defined]
    yield
    await lsp_client.shutdown_session()


@pytest_lsp.fixture(config=ClientServerConfig(server_command=[sys.executable, "-m", "pyta_lsp"]))
async def quiet_client(lsp_client: LanguageClient) -> AsyncGenerator[None, None]:
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=FIXTURES.as_uri(),
            initialization_options={"runOnOpen": False, "runOnSave": True, "configPath": ""},
        )
    )
    yield
    await lsp_client.shutdown_session()


def _open(client: LanguageClient, name: str) -> str:
    path = FIXTURES / name
    uri = path.as_uri()
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=path.read_text(encoding="utf-8")
            )
        )
    )
    return uri


async def test_open_publishes_diagnostics_honoring_embedded_config(client: LanguageClient) -> None:
    uri = _open(client, "course_style.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    diagnostics = client.diagnostics[uri]
    codes = {d.code for d in diagnostics}
    assert "E9989" in codes
    assert "E9999" not in codes
    assert all(d.source == "PythonTA" for d in diagnostics)
    pep8 = next(d for d in diagnostics if d.code == "E9989")
    assert pep8.range.start == types.Position(line=11, character=9)
    assert pep8.range.end == types.Position(line=11, character=len("    total=0"))
    assert pep8.code_description is not None
    assert pep8.code_description.href.endswith("#e9989")


async def test_close_clears_diagnostics(client: LanguageClient) -> None:
    uri = _open(client, "no_config.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert client.diagnostics[uri]
    client.text_document_did_close(
        types.DidCloseTextDocumentParams(text_document=types.TextDocumentIdentifier(uri=uri))
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert list(client.diagnostics[uri]) == []


async def test_syntax_error_is_reported(client: LanguageClient) -> None:
    uri = _open(client, "syntax_error.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    codes = [d.code for d in client.diagnostics[uri]]
    assert codes == ["E0001"]
    assert client.diagnostics[uri][0].range.start.line == 3


async def test_execute_command_checks_a_document(client: LanguageClient) -> None:
    uri = (FIXTURES / "no_config.py").as_uri()
    # Registers the notification future now, before the request that triggers the publish is sent.
    published = client.protocol.wait_for_notification_async(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    await client.workspace_execute_command_async(
        types.ExecuteCommandParams(command="pyta.check", arguments=[uri])
    )
    await published
    codes = {d.code for d in client.diagnostics[uri]}
    assert "E9999" in codes


async def test_server_advertises_check_command(client: LanguageClient) -> None:
    provider = client.server_capabilities.execute_command_provider  # type: ignore[attr-defined]
    assert provider is not None
    assert "pyta.check" in provider.commands


async def test_run_on_open_false_publishes_nothing(quiet_client: LanguageClient) -> None:
    import asyncio

    uri = _open(quiet_client, "no_config.py")
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(
            quiet_client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS), timeout=8
        )
    assert uri not in quiet_client.diagnostics or list(quiet_client.diagnostics[uri]) == []


async def test_precheck_failure_is_published_as_pyta_error(client: LanguageClient) -> None:
    uri = _open(client, "pylint_comment.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    diagnostics = list(client.diagnostics[uri])
    assert [d.code for d in diagnostics] == ["pyta-error"]
    assert diagnostics[0].range.start.line == 0
    assert "pylint:" in diagnostics[0].message


def test_workspace_root_follows_the_file_in_a_multi_root_workspace(tmp_path) -> None:
    from pyta_lsp.server import select_workspace_root

    first = tmp_path / "csc148"
    second = tmp_path / "csc110"
    for folder in (first, second):
        folder.mkdir()
    folders = [str(first), str(second)]

    assert select_workspace_root(folders, str(second / "a1" / "tally.py")) == str(second)
    assert select_workspace_root(folders, str(first / "tally.py")) == str(first)


def test_workspace_root_prefers_the_innermost_folder(tmp_path) -> None:
    from pyta_lsp.server import select_workspace_root

    outer = tmp_path / "work"
    inner = outer / "csc148"
    inner.mkdir(parents=True)

    assert select_workspace_root([str(outer), str(inner)], str(inner / "tally.py")) == str(inner)


def test_workspace_root_falls_back_when_the_file_is_outside_every_folder(tmp_path) -> None:
    from pyta_lsp.server import select_workspace_root

    folders = [str(tmp_path / "csc148"), str(tmp_path / "csc110")]

    assert select_workspace_root(folders, str(tmp_path / "scratch" / "x.py")) == folders[0]
    assert select_workspace_root([], str(tmp_path / "x.py")) is None


def _open_params(uri: str):
    return types.DidOpenTextDocumentParams(
        text_document=types.TextDocumentItem(uri=uri, language_id="python", version=1, text="x = 1\n")
    )


def test_automatic_checks_do_not_occupy_a_protocol_worker() -> None:
    # The pygls worker pool also serves the stdin reader, so a burst of opens that
    # each block a worker until their subprocess finishes stalls every later
    # message - close, shutdown, configuration - behind them.
    import threading
    import time

    from pyta_lsp import server as srv

    entered = threading.Event()
    release = threading.Event()

    class Blocking(srv.PytaLanguageServer):
        def check(self, uri: str) -> None:
            entered.set()
            release.wait(10)

    ls = Blocking()
    started = time.monotonic()
    try:
        srv.did_open(ls, _open_params("file:///tmp/a1.py"))
        elapsed = time.monotonic() - started
        assert entered.wait(5), "the check never ran"
    finally:
        release.set()

    assert elapsed < 0.5, f"did_open blocked for {elapsed:.1f}s waiting on the check"


async def test_open_checks_the_editor_buffer_not_the_file_on_disk(
    client: LanguageClient, tmp_path
) -> None:
    # A window reload restores unsaved edits, so the buffer and the file on disk can
    # differ. Checking disk while mapping positions onto the buffer puts squiggles on
    # lines the user never wrote.
    path = tmp_path / "dirty.py"
    path.write_text('"""Doc."""\nX = 1\n', encoding="utf-8")
    uri = path.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri,
                language_id="python",
                version=1,
                text='"""Doc."""\nimport os\n\nX = 1\n',
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    assert "E9999" in {d.code for d in client.diagnostics[uri]}


async def test_non_utf8_file_is_checked_through_the_staged_copy(
    client: LanguageClient, tmp_path
) -> None:
    # PythonTA reads the path it is given as UTF-8 and raises on anything else, so a
    # file carrying a cp1252 coding cookie could be parsed but never checked.
    # Staging the buffer as UTF-8 makes it checkable.
    from pyta_lsp.diagnostics import FAILURE_CODE

    text = '# -*- coding: cp1252 -*-\n"""Doc."""\nimport os\n\nNAME = "café"\n'
    path = tmp_path / "accented.py"
    path.write_bytes(text.encode("cp1252"))
    uri = path.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=text
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    codes = {d.code for d in client.diagnostics[uri]}
    assert FAILURE_CODE not in codes, "PythonTA still could not read the file"
    assert "E9999" in codes


async def test_a_package_module_is_not_given_false_import_errors(
    client: LanguageClient, tmp_path
) -> None:
    # A copy of a package module in a temp directory is not part of that package, so
    # its relative imports resolve to nothing and PythonTA invents an import error
    # the student cannot act on.
    package = tmp_path / "mypkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text(
        '"""Helper."""\n\n\ndef hi() -> int:\n    """Doc."""\n    return 1\n', encoding="utf-8"
    )
    source = '"""Doc."""\nfrom . import helper\n\nX = helper.hi()\n'
    module = package / "mod.py"
    module.write_text(source, encoding="utf-8")
    uri = module.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=source
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    assert "E0611" not in {d.code for d in client.diagnostics[uri]}


async def test_unsaved_changes_in_a_package_module_are_reported_not_guessed(
    client: LanguageClient, tmp_path
) -> None:
    # A package module cannot be checked from a copy, so when the buffer differs
    # from disk there is nothing correct to check. Checking disk anyway and mapping
    # the result onto the buffer puts diagnostics on lines the student never wrote.
    from pyta_lsp.diagnostics import FAILURE_CODE

    package = tmp_path / "mypkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    module = package / "mod.py"
    module.write_text('"""Doc."""\nX = 1\n', encoding="utf-8")
    uri = module.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri,
                language_id="python",
                version=1,
                text='"""Doc."""\nimport os\n\nX = 1\n',
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    assert FAILURE_CODE in {d.code for d in client.diagnostics[uri]}


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body


def test_the_server_exits_while_checks_are_in_flight() -> None:
    # The check pool's threads are not daemons, so the interpreter joins them on the
    # way out. A thread parked on a 60-second subprocess wait therefore holds the
    # whole process open, and closing a window mid-check orphans it with its mypy.
    import os
    import subprocess

    target = FIXTURES / "course_style.py"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "pyta_lsp"],
        stdin=subprocess.PIPE,
        # The runner subprocesses inherit these, so a pipe would keep the parent's
        # communicate() blocked long after the server itself is gone.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        proc.stdin.write(
            _frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "capabilities": {},
                        "processId": None,
                        "rootUri": FIXTURES.as_uri(),
                        "initializationOptions": {"runOnOpen": True, "runOnSave": True, "configPath": ""},
                    },
                }
            )
        )
        proc.stdin.flush()
        time.sleep(1.5)
        text = target.read_text(encoding="utf-8")
        for index in range(6):
            proc.stdin.write(
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "method": "textDocument/didOpen",
                        "params": {
                            "textDocument": {
                                "uri": f"{target.as_uri()}?{index}",
                                "languageId": "python",
                                "version": 1,
                                "text": text,
                            }
                        },
                    }
                )
            )
        proc.stdin.flush()
        time.sleep(1.0)

        proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}))
        proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "exit", "params": None}))
        proc.stdin.flush()

        started = time.monotonic()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise AssertionError("the server did not exit within 30s with checks in flight")
        elapsed = time.monotonic() - started
        # Six documents, two slots: four checks are queued behind the semaphore
        # when exit arrives, and none of them may spawn a runner of its own.
        assert elapsed < 5, f"exit took {elapsed:.1f}s and scales with open documents"
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdin.close()


def _dispatch_elapsed(method: str, params) -> float:
    """Hand one message to pygls the way the protocol does, and time the return.

    This is the point where pygls decides between running a handler inline on the
    asyncio loop and handing it to the thread pool, so it measures the thing that
    matters rather than the decorator.
    """
    from pyta_lsp import server as srv

    protocol = srv.server.protocol
    handler = protocol.fm.features[method]
    started = time.monotonic()
    protocol._execute_handler(
        msg_id="test", handler=handler, callback=lambda future: None, args=(params,)
    )
    return time.monotonic() - started


def test_did_close_does_not_block_the_event_loop(monkeypatch) -> None:
    # Closing a file cancels its check, and the tree-kill waits on taskkill for up
    # to 15 seconds. Inline on the loop that also reads stdin, that is 15 seconds
    # in which no other message is read.
    import threading

    from pyta_lsp import server as srv

    entered = threading.Event()
    release = threading.Event()

    def blocking_clear(uri: str) -> None:
        entered.set()
        release.wait(10)

    monkeypatch.setattr(srv.server, "clear", blocking_clear)
    params = types.DidCloseTextDocumentParams(
        text_document=types.TextDocumentIdentifier(uri="file:///tmp/a1.py")
    )
    try:
        elapsed = _dispatch_elapsed(types.TEXT_DOCUMENT_DID_CLOSE, params)
        assert entered.wait(5), "the close never ran"
    finally:
        release.set()

    assert elapsed < 0.5, f"did_close held the loop for {elapsed:.1f}s"


def test_shutdown_does_not_block_the_event_loop(monkeypatch) -> None:
    # Same kill, and shutdown arrives while every check is still in flight.
    import threading

    from pyta_lsp import server as srv

    entered = threading.Event()
    release = threading.Event()

    def blocking_stop() -> None:
        entered.set()
        release.wait(10)

    monkeypatch.setattr(srv.server, "stop_checks", blocking_stop)
    try:
        elapsed = _dispatch_elapsed(types.SHUTDOWN, None)
        assert entered.wait(5), "the shutdown never ran"
    finally:
        release.set()

    assert elapsed < 0.5, f"shutdown held the loop for {elapsed:.1f}s"


def test_the_shutdown_kill_still_finishes_before_the_process_does() -> None:
    # A daemon thread would be abandoned at interpreter exit with the runner and
    # its mypy still alive, which is the leak stop_checks exists to close.
    from pyta_lsp import server as srv

    ls = srv.PytaLanguageServer()
    thread = ls.begin_stop_checks()
    thread.join(5)

    assert not thread.daemon
    assert not thread.is_alive()


def test_the_check_command_does_not_occupy_a_protocol_worker() -> None:
    # Same pool as the stdin reader: an explicit check that waits on its subprocess
    # there delays every later message just as an automatic one would.
    import threading
    import time

    from pyta_lsp import server as srv

    entered = threading.Event()
    release = threading.Event()

    class Blocking(srv.PytaLanguageServer):
        def check(self, uri: str) -> None:
            entered.set()
            release.wait(10)

    ls = Blocking()
    started = time.monotonic()
    try:
        srv.command_check(ls, "file:///tmp/a1.py")
        elapsed = time.monotonic() - started
        assert entered.wait(5), "the check never ran"
    finally:
        release.set()

    assert elapsed < 0.5, f"the command blocked for {elapsed:.1f}s waiting on the check"


def test_closing_a_file_clears_its_diagnostics_before_the_kill_waits() -> None:
    # did_close runs off the loop now, so the same file can be reopened and checked
    # while the close is still parked in taskkill. Publishing the empty list after
    # that wait would wipe the fresh results.
    import threading

    from pyta_lsp import server as srv

    entered = threading.Event()
    release = threading.Event()
    published: list[list] = []
    ls = srv.PytaLanguageServer()

    def blocking_cancel(key: str) -> None:
        entered.set()
        release.wait(10)

    ls.scheduler.cancel = blocking_cancel  # type: ignore[method-assign]
    ls.text_document_publish_diagnostics = lambda params: published.append(params.diagnostics)  # type: ignore[method-assign]
    thread = threading.Thread(target=ls.clear, args=("file:///tmp/a1.py",))
    thread.start()
    try:
        assert entered.wait(5), "the close never reached the kill"
        assert published == [[]], "the diagnostics were still on screen when the kill started waiting"
    finally:
        release.set()
        thread.join(5)
        ls.stop_checks()


async def test_a_broken_course_config_is_visible_on_the_checked_file(client: LanguageClient, tmp_path) -> None:
    # The config's own messages must not be squiggled as if they were the
    # student's, but a config that fails to parse must not be silent either.
    (tmp_path / "cfg.txt").write_text("[MESSAGES CONTROL]\ndisable=not-a-real-message\n", encoding="utf-8")
    path = tmp_path / "a1.py"
    path.write_text(
        '"""Doc."""\nX = 1\n\nif __name__ == "__main__":\n'
        '    import python_ta\n    python_ta.check_all(config="cfg.txt")\n',
        encoding="utf-8",
    )
    uri = path.as_uri()
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=path.read_text(encoding="utf-8")
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    about_config = [d for d in client.diagnostics[uri] if d.code == "W0012"]
    assert len(about_config) == 1, [d.code for d in client.diagnostics[uri]]
    assert about_config[0].severity == types.DiagnosticSeverity.Information
    assert about_config[0].range.start.line == 0
    assert "cfg.txt" in about_config[0].message


def _bare_server(root):
    """A server with a workspace but no client, for driving check() directly."""
    from pygls.workspace import Workspace

    from pyta_lsp import server as srv

    ls = srv.PytaLanguageServer()
    ls.protocol._workspace = Workspace(root.as_uri())
    ls.notify_status = lambda *args, **kwargs: None  # type: ignore[method-assign]
    return ls


def _captured_spawn(ls) -> list:
    calls: list = []
    ls.scheduler.run = lambda key, argv, cwd: calls.append((argv, cwd)) or None  # type: ignore[method-assign]
    return calls


def test_the_runner_is_spawned_in_the_checked_file_s_own_directory(tmp_path) -> None:
    # sys.path[0] for `python -m` is the spawn directory, so on 3.10, where
    # PYTHONSAFEPATH does not exist, the cwd is what a student's string.py rides in
    # on. The staging directory holds only the copy.
    import os

    path = tmp_path / "a1.py"
    path.write_text('"""Doc."""\nX = 1\n', encoding="utf-8")
    ls = _bare_server(tmp_path)
    calls = _captured_spawn(ls)
    try:
        ls.check(path.as_uri())
    finally:
        ls.stop_checks()

    argv, cwd = calls[0]
    target = argv[3]
    assert os.path.dirname(target) != str(tmp_path), "the file was not staged"
    assert os.path.normcase(cwd) == os.path.normcase(os.path.dirname(target)), (
        f"spawned in {cwd}, not beside {target}"
    )


def test_a_package_module_is_spawned_in_its_own_package_directory(tmp_path) -> None:
    import os

    package = tmp_path / "mypkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    module = package / "mod.py"
    module.write_bytes(b'"""Doc."""\nX = 1\n')
    ls = _bare_server(tmp_path)
    calls = _captured_spawn(ls)
    try:
        ls.check(module.as_uri())
    finally:
        ls.stop_checks()

    argv, cwd = calls[0]
    assert os.path.normcase(argv[3]) == os.path.normcase(str(module))
    assert os.path.normcase(cwd) == os.path.normcase(os.path.dirname(str(module)))


def test_the_runner_env_keeps_the_spawn_directory_off_sys_path() -> None:
    from pyta_lsp.scheduler import runner_env

    assert runner_env()["PYTHONSAFEPATH"] == "1"


async def test_a_staged_check_sees_the_course_config_beside_the_file(
    client: LanguageClient, tmp_path
) -> None:
    # PythonTA's reset_linter loads config/.pylintrc from beside the file it is
    # given. The staged copy sits in a temp directory that has none, so the
    # extension checked the student against a config their own run never uses.
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".pylintrc").write_text(
        "[FORBIDDEN IMPORT]\nextra-imports = random\n", encoding="utf-8"
    )
    source = '"""Doc."""\nimport random\n\nX = random.random()\n'
    path = tmp_path / "a1.py"
    path.write_text(source, encoding="utf-8")
    uri = path.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=source
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    codes = {d.code for d in client.diagnostics[uri]}
    assert "E9999" not in codes, "the course config beside the file was not applied"


def test_the_local_config_lookup_matches_python_ta_s_own(tmp_path) -> None:
    # The server cannot call python_ta.config.find_local_config without importing
    # pylint and astroid into a process that lives for the session, so it carries
    # its own copy of the lookup. This is what keeps the copy honest.
    import os

    from python_ta.config import find_local_config as pyta_find

    from pyta_lsp.server import find_local_config

    assert find_local_config(str(tmp_path)) is None
    assert pyta_find(str(tmp_path)) is None
    (tmp_path / "config").mkdir()
    for name in ("pyproject.toml", "pylintrc", ".pylintrc"):
        (tmp_path / "config" / name).write_text("", encoding="utf-8")
        ours = find_local_config(str(tmp_path))
        theirs = pyta_find(str(tmp_path))
        assert ours is not None and theirs is not None
        assert os.path.normcase(ours) == os.path.normcase(theirs), name


_COOKIE_LINE = 'NOM = "caféééééé ' + "x" * 61 + '"'


async def test_a_non_utf8_cookie_does_not_survive_into_the_utf8_staged_copy(
    client: LanguageClient, tmp_path
) -> None:
    # The copy is written as UTF-8. A cp1252 cookie riding along makes the
    # tokenizer decode those bytes as cp1252, so every non-ASCII character counts
    # twice: a 79-character line becomes 85 and C0301 appears on a line the
    # student's own run never complains about.
    body = '"""Doc."""\n' + _COOKIE_LINE + "\nprint(NOM)\n"
    results = {}
    for name, cookie in (("cp1252.py", "cp1252"), ("utf8.py", "utf-8")):
        source = f"# -*- coding: {cookie} -*-\n" + body
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        uri = path.as_uri()
        client.text_document_did_open(
            types.DidOpenTextDocumentParams(
                text_document=types.TextDocumentItem(
                    uri=uri, language_id="python", version=1, text=source
                )
            )
        )
        await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
        results[name] = sorted(str(d.code) for d in client.diagnostics[uri])

    assert results["cp1252.py"] == results["utf8.py"], results


def test_a_coding_cookie_is_pointed_at_utf8_without_moving_any_line() -> None:
    from pyta_lsp.server import normalise_coding_cookie

    assert normalise_coding_cookie("# -*- coding: cp1252 -*-\nX = 1\n") == (
        "# -*- coding: utf-8 -*-\nX = 1\n"
    )
    assert normalise_coding_cookie("#!/usr/bin/env python\n# coding: latin-1\nX = 1\n") == (
        "#!/usr/bin/env python\n# coding: utf-8\nX = 1\n"
    )
    assert normalise_coding_cookie("# -*- coding: utf-8 -*-\nX = 1\n") == (
        "# -*- coding: utf-8 -*-\nX = 1\n"
    )
    # A cookie is only a cookie in the first two lines, and only before real code.
    assert normalise_coding_cookie("X = 1\n# coding: cp1252\n") == "X = 1\n# coding: cp1252\n"
    assert normalise_coding_cookie("# -*- coding: cp1252 -*-\r\nX = 1\r\n").count("\r\n") == 2


async def test_a_saved_package_module_with_mixed_line_endings_is_still_checked(
    client: LanguageClient, tmp_path
) -> None:
    # The editor normalises a document to one EOL, so a file whose bytes mix \r\n
    # and \n never equals the buffer byte for byte even when it is saved. A package
    # module cannot be staged, so that comparison is what decides between real
    # diagnostics and "save the file first".
    from pyta_lsp.diagnostics import FAILURE_CODE

    package = tmp_path / "mypkg"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"")
    module = package / "mod.py"
    module.write_bytes(b'"""Doc."""\r\nimport os\n\r\nX = 1\n')
    uri = module.as_uri()

    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri,
                language_id="python",
                version=1,
                text='"""Doc."""\nimport os\n\nX = 1\n',
            )
        )
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)

    codes = {d.code for d in client.diagnostics[uri]}
    assert FAILURE_CODE not in codes, "a saved file was reported as having unsaved changes"
    assert "E9999" in codes


def test_matches_disk_ignores_the_editor_s_line_ending_normalisation(tmp_path) -> None:
    from pyta_lsp.server import matches_disk

    path = tmp_path / "mod.py"
    path.write_bytes(b'"""Doc."""\r\nX = 1\n\rY = 2\n')

    assert matches_disk(str(path), '"""Doc."""\nX = 1\n\nY = 2\n')
    assert not matches_disk(str(path), '"""Doc."""\nX = 2\n\nY = 2\n')


def test_a_failure_after_the_checking_status_still_ends_the_check(tmp_path) -> None:
    # mkdtemp, the staged write and Popen can all fail. Returning from any of them
    # leaves no diagnostics and no terminal status, so the status bar spins for
    # the rest of the session and the file never shows a result again.
    from pyta_lsp.diagnostics import FAILURE_CODE

    path = tmp_path / "a1.py"
    path.write_bytes(b'"""Doc."""\nX = 1\n')
    ls = _bare_server(tmp_path)
    statuses: list = []
    published: list = []
    ls.notify_status = lambda uri, state, count=None: statuses.append(state)  # type: ignore[method-assign]
    ls.text_document_publish_diagnostics = lambda params: published.append(params.diagnostics)  # type: ignore[method-assign]
    ls.log_to_client = lambda *args, **kwargs: None  # type: ignore[method-assign]

    def boom(*args, **kwargs):
        raise OSError("no space left on device")

    ls.scheduler.run = boom  # type: ignore[method-assign]
    try:
        ls.check(path.as_uri())
    finally:
        ls.stop_checks()

    assert statuses == ["checking", "done"], statuses
    assert [d.code for d in published[0]] == [FAILURE_CODE]
    assert "no space left on device" in published[0][0].message
