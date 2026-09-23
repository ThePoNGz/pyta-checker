"""Run the runner subprocess per document. A newer request kills and supersedes an older one."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from typing import Any, Callable

from .paths import mypy_cache_dir

Spawn = Callable[[list[str], str], subprocess.Popen]

# Identifies which run produced a result, so a stale thread cannot republish it.
GENERATION_KEY = "__generation__"


def runner_env() -> dict[str, str]:
    """The environment the runner subprocess gets."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 3.11+. Keeps the spawn directory off sys.path[0] before the runner imports
    # anything, and mypy inherits it, so a string.py or random.py sitting beside
    # the checked file never gets imported. Ignored on 3.10, where the cwd the
    # server picks is what limits the damage.
    env["PYTHONSAFEPATH"] = "1"
    # We hard code this path so an environment variable like MYPY_CACHE_DIR doesnt
    # make student checks fight over the same cache directory.
    env["MYPY_CACHE_DIR"] = mypy_cache_dir()
    return env


def default_spawn(argv: list[str], cwd: str) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        # Its own process group / session so the whole tree can be killed at once.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=runner_env(),
        **kwargs,
    )


def _kill(proc: subprocess.Popen) -> None:
    """Kill the runner and everything it spawned.

    PythonTA runs mypy in a subprocess of its own with no timeout, so killing
    only the direct child leaves that mypy alive and outside max_parallel.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            if completed.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _reap_later(proc: subprocess.Popen) -> None:
    """Hand a process the worker could not reap to a thread that can wait on it.

    Neither reaping nor closing can happen on the worker. A tree kill that did not
    take leaves a grandchild holding the write end of the pipes, so the Popen
    reader threads never finish and both communicate() and pipe.close() block
    until they do. An untimed communicate() on a daemon thread closes the pipes by
    itself once the process finally dies, and costs nothing if it never does.
    """
    threading.Thread(target=_reap, args=(proc,), name="pyta-reap", daemon=True).start()


def _reap(proc: subprocess.Popen) -> None:
    try:
        proc.communicate()
    except (OSError, ValueError):
        pass


def _failure(error: str, log: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "messages": [], "log": log, "warnings": [], "traceback": None}


def _interpret(out: bytes, err: bytes, returncode: int | None, timed_out: bool, timeout: float) -> dict[str, Any]:
    stderr = err.decode("utf-8", errors="replace").strip()
    if timed_out:
        return _failure(f"timed out after {int(timeout)} seconds", stderr)
    stdout = out.decode("utf-8", errors="replace").strip()
    if returncode != 0 or not stdout:
        last = stderr.splitlines()[-1] if stderr else f"runner exited with code {returncode}"
        return _failure(last, stderr)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return _failure("runner output was not JSON", stdout[-2000:])
    if not isinstance(data, dict):
        return _failure("runner output had an unexpected shape", stdout[-2000:])
    return data


class CheckScheduler:
    """Runs one runner subprocess per document and keeps only the newest run alive.

    Attributes:
        _spawn: how a runner gets started, swapped out in tests.
        _timeout: seconds a single run gets before we kill it.
        _slots: caps how many runners can be alive at once.
        _lock: guards every dict below.
        _generation: the newest version ID per document key.
        _completed: the version ID of the last run that finished per key.
        _procs: the live process per key, when there is one.
        _stopped: True after cancel_all, so nothing new can spawn.
    """

    def __init__(self, spawn: Spawn = default_spawn, timeout: float = 60.0, max_parallel: int = 2) -> None:
        self._spawn = spawn
        self._timeout = timeout
        self._slots = threading.BoundedSemaphore(max_parallel)
        self._lock = threading.Lock()
        self._generation: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._stopped = False

    def reserve(self, key: str) -> int:
        """Grab the latest version ID for this key and kill anything currently running for it.

        If a caller can crash before it reaches run(), like staging a copy or writing
        it, it needs to claim a version ID upfront. If we dont do that it wont know
        if its own error message is still relevant.

        Args:
            key: the document this run belongs to, normally the URI.

        Returns:
            The new version ID to hand back to run(), fail() or guard().
        """
        with self._lock:
            generation = self._generation.get(key, 0) + 1
            self._generation[key] = generation
            previous = self._procs.pop(key, None)
        if previous is not None:
            _kill(previous)
        return generation

    def fail(self, key: str, generation: int, action: Callable[[], None]) -> bool:
        """Finish this version ID with no result and run action, if it is still the newest.

        The action runs under the lock the same way guard() does. Deciding inside the
        lock and publishing outside it let a did_close land in between, so the failure
        got published onto a document that had just been cleared.

        Args:
            key: the document key.
            generation: the version ID the caller reserved.
            action: what to run while the lock is held, normally publishing the failure.

        Returns:
            True when the action ran, False when a newer run already took the key.
        """
        with self._lock:
            if self._generation.get(key) != generation:
                return False
            self._completed[key] = generation
            action()
            return True

    def run(
        self, key: str, argv: list[str], cwd: str, generation: int | None = None
    ) -> dict[str, Any] | None:
        """Run the runner for this key and hand back what it printed.

        Args:
            key: the document key.
            argv: the command line for the runner subprocess.
            cwd: where to start the runner, which decides sys.path[0] on 3.10.
            generation: a version ID from reserve(), or None to claim one here.

        Returns:
            The parsed result with its version ID under GENERATION_KEY, or None when a
            newer run took the key or the scheduler was stopped.
        """
        if generation is None:
            generation = self.reserve(key)

        with self._slots:
            with self._lock:
                # A thread can get stuck here for a few minutes. Spawning after
                # cancel_all, or after a newer request took this key, means starting
                # a runner nothing can kill. The check, the spawn and the registration
                # are one critical section so a cancel_all cannot snapshot _procs
                # between them and miss a process about to exist.
                if self._stopped or self._generation.get(key) != generation:
                    return None
                proc = self._spawn(argv, cwd)
                self._procs[key] = proc

            timed_out = False
            try:
                out, err = proc.communicate(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                _kill(proc)
                try:
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    out, err = b"", b""
                    _reap_later(proc)
                timed_out = True

        with self._lock:
            if self._procs.get(key) is proc:
                del self._procs[key]
            if self._generation[key] != generation:
                return None
            self._completed[key] = generation
        result = _interpret(out, err, proc.returncode, timed_out, self._timeout)
        result[GENERATION_KEY] = generation
        return result

    def guard(self, key: str, generation: int, action: Callable[[], None]) -> bool:
        """Run action under the lock, but only if this version ID is still the newest and the last one to finish.

        Comparing against the version ID the caller holds is what stops a slow thread
        with an older result from publishing it over newer diagnostics.

        Args:
            key: the document key.
            generation: the version ID this caller ran with.
            action: what to run while the lock is held, normally publishing diagnostics.

        Returns:
            True when the action ran, False when the result is stale.
        """
        with self._lock:
            completed = self._completed.get(key)
            if completed is None or completed != generation:
                return False
            if self._generation.get(key) != completed:
                return False
            action()
            return True

    def cancel_all(self) -> None:
        """Stop every check, the ones still queued for a slot included.

        Bumping only the keys that already hold a process left a queued thread
        looking current, so it spawned a runner after shutdown and then waited
        out the timeout on it.
        """
        with self._lock:
            self._stopped = True
            for key in self._generation:
                self._generation[key] += 1
            procs = list(self._procs.values())
            self._procs.clear()
        for proc in procs:
            _kill(proc)

    def cancel(self, key: str) -> None:
        """Stop the check on one document and bump its version ID."""
        with self._lock:
            self._generation[key] = self._generation.get(key, 0) + 1
            proc = self._procs.pop(key, None)
        if proc is not None:
            _kill(proc)
