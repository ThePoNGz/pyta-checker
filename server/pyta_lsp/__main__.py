"""Entry point for `python -m pyta_lsp` and the `pyta-lsp` console script."""
from __future__ import annotations

import os
import sys


def drop_cwd_from_path(cwd: str | None = None, path: list[str] = sys.path) -> None:
    """Take the start directory out of sys.path, wherever it came from.

    An editor starts the server from the project root. On 3.10 `python -m` puts
    that root first on sys.path, and on any version a PYTHONPATH from the shell
    can hold it, so a student file called json.py there would be imported in
    place of the standard library one. This process never needs the project on
    its path. What runpy imports before this runs (types, operator and a few
    more) is only covered by the -c launcher in scripts/bundle.py.
    """
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
    from . import __version__
    from .server import server

    # Editors that pick the interpreter themselves show this in their server log,
    # and the Zed extension passes anything else the user should know the same way.
    log = logging.getLogger("pyta_lsp")
    log.info("pyta-lsp %s running under %s", __version__, sys.executable)
    notice = os.environ.get("PYTA_LSP_NOTICE")
    if notice:
        log.warning("%s", notice)

    try:
        server.start_io()
    finally:
        # The editor can disappear without sending shutdown, and check threads arent
        # daemons so nothing else would release them.
        server.stop_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
