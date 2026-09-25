import logging

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


def test_drop_cwd_from_path_defers_to_safe_path(tmp_path, monkeypatch) -> None:
    # With PYTHONSAFEPATH the interpreter never added the cwd, so an entry equal to
    # it was put there on purpose by whoever launched us.
    from pyta_lsp.__main__ import drop_cwd_from_path

    monkeypatch.setattr("sys.flags", type("Flags", (), {"safe_path": True})())
    path = [str(tmp_path)]

    drop_cwd_from_path(str(tmp_path), path)

    assert path == [str(tmp_path)]
