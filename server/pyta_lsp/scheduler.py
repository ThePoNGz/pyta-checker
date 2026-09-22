"""Run the runner subprocess per document. A newer request kills and supersedes an older one."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Any, Callable

Spawn = Callable[[list[str], str], subprocess.Popen]


def runner_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def default_spawn(argv: list[str], cwd: str) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
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
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
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
    def __init__(self, spawn: Spawn = default_spawn, timeout: float = 60.0) -> None:
        self._spawn = spawn
        self._timeout = timeout
        self._lock = threading.Lock()
        self._generation: dict[str, int] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    def run(self, key: str, argv: list[str], cwd: str) -> dict[str, Any] | None:
        with self._lock:
            generation = self._generation.get(key, 0) + 1
            self._generation[key] = generation
            previous = self._procs.pop(key, None)
        if previous is not None:
            _kill(previous)

        proc = self._spawn(argv, cwd)
        with self._lock:
            superseded = self._generation[key] != generation
            if not superseded:
                self._procs[key] = proc
        if superseded:
            _kill(proc)
            return None

        timed_out = False
        try:
            out, err = proc.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            out, err = proc.communicate()
            timed_out = True

        with self._lock:
            if self._procs.get(key) is proc:
                del self._procs[key]
            if self._generation[key] != generation:
                return None
        return _interpret(out, err, proc.returncode, timed_out, self._timeout)

    def cancel(self, key: str) -> None:
        with self._lock:
            self._generation[key] = self._generation.get(key, 0) + 1
            proc = self._procs.pop(key, None)
        if proc is not None:
            _kill(proc)
