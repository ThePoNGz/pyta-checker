import logging
import os

import pytest

from pyta_lsp.__main__ import configure_logging


def test_pygls_logging_is_quiet() -> None:
    configure_logging()
    assert logging.getLogger("pygls").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("pyta_lsp").getEffectiveLevel() <= logging.INFO


class _FakeServer:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.stopped = 0

    def start_io(self) -> None:
        if self.failure is not None:
            raise self.failure

    def stop_checks(self) -> None:
        self.stopped += 1


def test_main_releases_checks_when_the_connection_closes(monkeypatch) -> None:
    # The editor can vanish without ever sending shutdown. The check threads are
    # not daemons, so if nothing releases them the server outlives the editor.
    from pyta_lsp import __main__ as entry

    fake = _FakeServer()
    monkeypatch.setattr("pyta_lsp.server.server", fake)

    assert entry.main() == 0
    assert fake.stopped == 1


def test_main_logs_the_interpreter_it_runs_under(monkeypatch, caplog) -> None:
    import sys

    from pyta_lsp import __main__ as entry

    monkeypatch.setattr("pyta_lsp.server.server", _FakeServer())
    with caplog.at_level(logging.INFO, logger="pyta_lsp"):
        entry.main()

    assert any(sys.executable in record.getMessage() for record in caplog.records)


def test_main_releases_checks_when_the_loop_raises(monkeypatch) -> None:
    import pytest

    from pyta_lsp import __main__ as entry

    fake = _FakeServer(failure=RuntimeError("pipe died"))
    monkeypatch.setattr("pyta_lsp.server.server", fake)

    with pytest.raises(RuntimeError):
        entry.main()
    assert fake.stopped == 1


def test_drop_cwd_from_path_removes_only_the_cwd_entries(tmp_path, monkeypatch) -> None:
    from pyta_lsp.__main__ import drop_cwd_from_path

    monkeypatch.setattr("sys.flags", type("Flags", (), {"safe_path": False})())
    other = str(tmp_path / "elsewhere")
    path = [str(tmp_path), "", other, str(tmp_path)]

    drop_cwd_from_path(str(tmp_path), path)

    assert path == ["", other]


def test_drop_cwd_from_path_treats_the_empty_entry_as_the_cwd(tmp_path, monkeypatch) -> None:
    from pyta_lsp.__main__ import drop_cwd_from_path

    monkeypatch.setattr("sys.flags", type("Flags", (), {"safe_path": False})())
    monkeypatch.chdir(tmp_path)
    path = ["", "/somewhere/else"]

    drop_cwd_from_path(None, path)

    assert path == ["/somewhere/else"]


def test_drop_cwd_from_path_strips_the_cwd_even_under_safe_path(tmp_path, monkeypatch) -> None:
    # PYTHONSAFEPATH only stops the interpreter adding the cwd itself. A project
    # root that arrives through PYTHONPATH (export PYTHONPATH=$PWD is common
    # course advice) still outranks the standard library, and this process never
    # needs the project on its path.
    from pyta_lsp.__main__ import drop_cwd_from_path

    monkeypatch.setattr("sys.flags", type("Flags", (), {"safe_path": True})())
    other = str(tmp_path / "elsewhere")
    path = [other, str(tmp_path)]

    drop_cwd_from_path(str(tmp_path), path)

    assert path == [other]


def test_main_logs_a_notice_from_the_editor(monkeypatch, caplog) -> None:
    # The Zed extension has no log of its own, so what it wants the user to know
    # about the server it picked rides in on an environment variable.
    from pyta_lsp import __main__ as entry

    monkeypatch.setattr("pyta_lsp.server.server", _FakeServer())
    monkeypatch.setenv("PYTA_LSP_NOTICE", "Using the earlier download for now.")
    with caplog.at_level(logging.INFO, logger="pyta_lsp"):
        entry.main()

    notices = [r for r in caplog.records if "earlier download" in r.getMessage()]
    assert notices and notices[0].levelno == logging.WARNING


def test_the_environment_is_passed_through_untouched(tmp_path, monkeypatch) -> None:
    # The runner gets the same PYTHONPATH the students own python would, project
    # root included, so a check resolves imports exactly as their run does. The
    # server only guards its own sys.path against the directory it starts in.
    import importlib

    from pyta_lsp import __main__ as entry

    value = os.pathsep.join([str(tmp_path / "libs"), str(tmp_path), ""])
    monkeypatch.setenv("PYTHONPATH", value)
    monkeypatch.chdir(tmp_path)

    importlib.reload(entry)

    assert os.environ["PYTHONPATH"] == value
    assert not hasattr(entry, "demote_cwd_in_pythonpath")


def test_resolved_falls_back_when_realpath_raises(tmp_path, monkeypatch) -> None:
    # ntpath.realpath re-raises some volume errors on 3.10 to 3.12, which abspath
    # never does, and the server must still come up on such a drive.
    from pyta_lsp import __main__ as entry

    def broken(path: str) -> str:
        raise OSError(1005, "unrecognized volume")

    monkeypatch.setattr(entry.os.path, "realpath", broken)
    assert entry._resolved(str(tmp_path / "x")) == os.path.normcase(os.path.abspath(str(tmp_path / "x")))


def test_drop_cwd_from_path_sees_through_a_symlink(tmp_path, monkeypatch) -> None:
    # A shell PYTHONPATH=$PWD holds the logical path and os.getcwd() the physical
    # one, so comparing without resolving would keep the project on the path.
    import sys

    from pyta_lsp.__main__ import drop_cwd_from_path

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    path = [str(link), "/elsewhere"]
    drop_cwd_from_path(str(real), path)
    assert path == ["/elsewhere"]
