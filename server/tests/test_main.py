import logging

from pyta_lsp.__main__ import configure_logging


def test_pygls_logging_is_quiet() -> None:
    configure_logging()
    assert logging.getLogger("pygls").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("pyta_lsp").getEffectiveLevel() <= logging.INFO
