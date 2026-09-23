"""Entry point for `python -m pyta_lsp` and the `pyta-lsp` console script."""
from __future__ import annotations

import logging
import sys


def configure_logging() -> None:
    """Send logs to stderr. pygls logs every outgoing JSON-RPC body at INFO so we keep it at WARNING."""
    logging.basicConfig(
        level=logging.INFO,
        format="[pyta-lsp] %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("pyta_lsp").setLevel(logging.INFO)
    logging.getLogger("pygls").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    """Set up logging, serve over stdio, then make sure no check outlives us."""
    configure_logging()
    from .server import server

    try:
        server.start_io()
    finally:
        # The editor can disappear without sending shutdown, and check threads arent
        # daemons so nothing else would release them.
        server.stop_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
