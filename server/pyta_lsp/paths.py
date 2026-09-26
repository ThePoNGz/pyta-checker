"""Paths shared by the server and the runner it spawns."""
from __future__ import annotations

import getpass
import os
import tempfile

# Three copies of this: here, scripts/bundle.py (SERVER_LAUNCHER, for the tarball
# check) and zed/src/logic.rs (the Zed extension). Tests keep them equal. One line
# on purpose, since a .bat target on Windows cannot take an argument with a newline
# in it, so the helper with the realpath fallback (for volumes where ntpath.realpath
# raises on 3.10 to 3.12) is defined through exec.
_LAUNCHER = r'''import os, sys; exec("def _r(p):\n    try:\n        return os.path.normcase(os.path.realpath(p))\n    except OSError:\n        return os.path.normcase(os.path.abspath(p))"); here = _r(os.getcwd()); sys.path[:] = [p for p in sys.path if p and _r(p) != here]; import runpy; runpy.run_module('%s', run_name='__main__', alter_sys=True)'''


def module_launcher(module: str) -> list[str]:
    """The arguments that run `python -m module` with the start directory kept off sys.path.

    With -m the start directory is on sys.path before runpy imports anything, so
    a student types.py there is imported in place of the standard library one on
    3.10, and on any version without PYTHONSAFEPATH. This clears it first and
    imports nothing until it has. Arguments after it reach the module as with -m.
    """
    return ["-c", _LAUNCHER % module]


def _user_tag() -> str:
    """A stable per-user component for paths under the shared temp directory."""
    try:
        name = getpass.getuser()
    except (OSError, KeyError, ImportError):
        uid = getattr(os, "getuid", None)
        name = str(uid()) if uid is not None else ""
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return cleaned or "default"


def mypy_cache_dir() -> str:
    """Where mypy can keep its cache, no matter who runs the check or from where.

    On a shared /tmp the first user who makes a fixed cache directory owns it and
    mypy then fails for everyone else. python_ta ignores the mypy return code, so
    E9951-E9956 would vanish with no error shown. Left unset, mypy writes a
    .mypy_cache into whatever directory the check runs from, which for an in
    process check is the directory of the caller.
    """
    return os.path.join(tempfile.gettempdir(), f"pyta-checker-mypy-cache-{_user_tag()}")
