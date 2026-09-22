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


def test_main_releases_checks_when_the_loop_raises(monkeypatch) -> None:
    import pytest

    from pyta_lsp import __main__ as entry

    fake = _FakeServer(failure=RuntimeError("pipe died"))
    monkeypatch.setattr("pyta_lsp.server.server", fake)

    with pytest.raises(RuntimeError):
        entry.main()
    assert fake.stopped == 1
