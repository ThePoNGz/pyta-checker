"""Paths shared by the server and the runner it spawns."""
from __future__ import annotations

import getpass
import os
import tempfile


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
    """Where mypy may keep its cache, whoever runs the check and from where.

    On a shared /tmp the first user to create a fixed cache directory owns it,
    and mypy then fails for everyone else. python_ta ignores mypy's return code,
    so E9951-E9956 would vanish with no error shown. Unset, mypy writes a
    .mypy_cache into whatever directory the check is run from, which for an
    in-process check is the caller's own.
    """
    return os.path.join(tempfile.gettempdir(), f"pyta-checker-mypy-cache-{_user_tag()}")
