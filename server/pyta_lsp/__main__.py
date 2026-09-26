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
    target = _resolved(os.getcwd() if cwd is None else cwd)
    for entry in [p for p in path if _resolved(p or os.curdir) == target]:
        path.remove(entry)


DEMOTED_VAR = "PYTA_LSP_DEMOTED_PATH"


def demote_cwd_in_pythonpath(cwd: str | None = None, environ: dict[str, str] = os.environ) -> None:
    """Move the start directory from the PYTHONPATH the runner inherits to the back of its path.

    Every check runs in a subprocess that takes PYTHONPATH from the environment,
    not from this process's sys.path, so a project root left in the variable
    would shadow the standard library in each check while the server itself
    came up fine. It cannot simply go, because a course that says export
    PYTHONPATH=$PWD relies on it for imports of packages at the root, the way the
    students own PythonTA run resolves them. So the runner gets it separately
    and appends it after everything else. An empty entry means the cwd to Python.
    """
    value = environ.get("PYTHONPATH")
    if not value:  # Python ignores an empty PYTHONPATH, so it does not mean the cwd
        return
    start = os.getcwd() if cwd is None else cwd
    target = _resolved(start)
    kept: list[str] = []
    demoted = False
    for entry in value.split(os.pathsep):
        if entry and _resolved(entry) != target:
            kept.append(entry)
        else:
            demoted = True
    if kept:
        environ["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        del environ["PYTHONPATH"]
    if demoted:
        environ[DEMOTED_VAR] = _real(start)


def _real(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:  # some Windows volumes on 3.10 to 3.12
        return os.path.abspath(path)


def _resolved(path: str) -> str:
    # A shell reports the logical path and getcwd the physical one, so only a
    # resolved comparison sees that PYTHONPATH=$PWD is the start directory.
    return os.path.normcase(_real(path))


drop_cwd_from_path()
demote_cwd_in_pythonpath()

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
