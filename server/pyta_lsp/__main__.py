"""Entry point for `python -m pyta_lsp` and the `pyta-lsp` console script."""
from __future__ import annotations

import os
import sys


def drop_cwd_from_path(cwd: str | None = None, path: list[str] = sys.path) -> None:
    """Take the directory `python -m` put at the front of sys.path back out.

    An editor starts the server from the project root, and on 3.10 there is no
    PYTHONSAFEPATH, so a student file called json.py at that root would be imported
    in place of the standard library one. This runs before anything the server
    needs gets imported, so the shadowing never happens.
    """
    if getattr(sys.flags, "safe_path", False):
        return
    target = os.path.normcase(os.path.abspath(os.getcwd() if cwd is None else cwd))
    for entry in [p for p in path if os.path.normcase(os.path.abspath(p or os.curdir)) == target]:
        path.remove(entry)


drop_cwd_from_path()

import logging  # noqa: E402


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
