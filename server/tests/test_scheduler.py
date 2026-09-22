import os
import sys
import threading
import time
from pathlib import Path

from pyta_lsp.scheduler import GENERATION_KEY, CheckScheduler


def _echo_argv(tag: str, delay: float = 0.0) -> list[str]:
    code = (
        "import json, sys, time; "
        f"time.sleep({delay}); "
        f"sys.stdout.write(json.dumps({{'ok': True, 'messages': [], 'tag': {tag!r}}}))"
    )
    return [sys.executable, "-c", code]


def test_run_returns_parsed_json(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    result = scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    assert result.pop(GENERATION_KEY) == 1
    assert result == {"ok": True, "messages": [], "tag": "one"}


def test_newer_request_supersedes_older(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def slow() -> None:
        results["first"] = scheduler.run("doc", _echo_argv("slow", delay=5), str(tmp_path))

    thread = threading.Thread(target=slow)
    thread.start()
    time.sleep(0.5)
    results["second"] = scheduler.run("doc", _echo_argv("fast"), str(tmp_path))
    thread.join(timeout=30)
    assert results["first"] is None
    assert results["second"]["tag"] == "fast"  # type: ignore[index]


def test_timeout_is_reported(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=0.5)
    result = scheduler.run("doc", [sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path))
    assert result is not None
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_nonzero_exit_uses_last_stderr_line(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys; sys.stderr.write('boom\\nlast line\\n'); sys.exit(2)"]
    result = CheckScheduler(timeout=30).run("doc", argv, str(tmp_path))
    assert result["ok"] is False
    assert result["error"] == "last line"


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "print('not json')"]
    result = CheckScheduler(timeout=30).run("doc", argv, str(tmp_path))
    assert result["ok"] is False
    assert "not JSON" in result["error"]


def test_different_keys_run_independently(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def run(key: str) -> None:
        results[key] = scheduler.run(key, _echo_argv(key, delay=1), str(tmp_path))

    threads = [threading.Thread(target=run, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results["a"]["tag"] == "a"  # type: ignore[index]
    assert results["b"]["tag"] == "b"  # type: ignore[index]


def test_cancel_kills_in_flight(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def slow() -> None:
        results["r"] = scheduler.run("doc", _echo_argv("slow", delay=10), str(tmp_path))

    thread = threading.Thread(target=slow)
    thread.start()
    time.sleep(0.5)
    scheduler.cancel("doc")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert results["r"] is None


def test_guard_runs_action_after_current_run(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    result = scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    calls: list[str] = []
    assert scheduler.guard("doc", result[GENERATION_KEY], lambda: calls.append("published")) is True
    assert calls == ["published"]


def test_guard_skips_action_after_cancel(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    result = scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    scheduler.cancel("doc")
    calls: list[str] = []
    assert scheduler.guard("doc", result[GENERATION_KEY], lambda: calls.append("published")) is False
    assert calls == []


def test_guard_skips_action_for_unknown_key() -> None:
    assert CheckScheduler(timeout=30).guard("never-run", 1, lambda: None) is False


def test_parallel_runs_are_bounded(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30, max_parallel=2)
    started = time.monotonic()
    threads = [
        threading.Thread(target=scheduler.run, args=(key, _echo_argv(key, delay=1.5), str(tmp_path)))
        for key in ("a", "b", "c")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - started
    assert elapsed >= 2.5, f"three 1.5s runs with a limit of two must take two rounds, took {elapsed:.1f}s"
    assert elapsed < 6, f"runs should still overlap, took {elapsed:.1f}s"


def test_runner_env_forces_utf8_and_redirects_mypy_cache() -> None:
    from pyta_lsp.scheduler import runner_env

    env = runner_env()
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    assert "pyta-checker-mypy-cache" in os.path.basename(env["MYPY_CACHE_DIR"])


def test_guard_rejects_a_result_from_a_superseded_generation(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    first = scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    second = scheduler.run("doc", _echo_argv("two"), str(tmp_path))
    calls: list[str] = []

    stale_published = scheduler.guard("doc", first[GENERATION_KEY], lambda: calls.append("stale"))
    fresh_published = scheduler.guard("doc", second[GENERATION_KEY], lambda: calls.append("fresh"))

    assert stale_published is False
    assert fresh_published is True
    assert calls == ["fresh"]


def _grandchild_argv(marker: Path, sleep: float = 4.0) -> list[str]:
    inner = f"import time, pathlib; time.sleep({sleep}); pathlib.Path({str(marker)!r}).write_text('ran')"
    outer = f"import subprocess, sys; subprocess.run([sys.executable, '-c', {inner!r}], capture_output=True)"
    return [sys.executable, "-c", outer]


def test_kill_takes_down_grandchildren(tmp_path: Path) -> None:
    # PythonTA shells out to mypy on every check, and that subprocess has no
    # timeout of its own, so killing only the direct child leaks a live mypy
    # process for every superseded or timed-out run.
    marker = tmp_path / "GRANDCHILD_RAN.txt"
    scheduler = CheckScheduler(timeout=1)

    result = scheduler.run("doc", _grandchild_argv(marker), str(tmp_path))

    assert result["error"].startswith("timed out")
    time.sleep(6)
    assert not marker.exists()


def test_kill_falls_back_when_taskkill_reports_failure(monkeypatch) -> None:
    # taskkill exits nonzero when it cannot reach the tree. subprocess.run does not
    # raise on that, so returning regardless skipped the fallback and left the
    # runner alive.
    import subprocess as sp

    from pyta_lsp import scheduler

    if sys.platform != "win32":
        import pytest

        pytest.skip("taskkill is the win32 branch")

    killed: list[str] = []

    class FakeProc:
        pid = 4321

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            killed.append("kill")

    monkeypatch.setattr(sp, "run", lambda argv, **kw: sp.CompletedProcess(argv, 1, b"", b"ERROR: not found"))
    scheduler._kill(FakeProc())

    assert killed == ["kill"]


def test_mypy_cache_dir_is_per_user(monkeypatch) -> None:
    # /tmp is shared on a lab machine, so a fixed cache directory belongs to
    # whoever created it first and mypy then fails for every other user. PythonTA
    # ignores mypy's return code, so E9951-E9956 disappear without a word.
    import getpass

    from pyta_lsp.scheduler import runner_env

    monkeypatch.setattr(getpass, "getuser", lambda: "student1")
    first = runner_env()["MYPY_CACHE_DIR"]
    monkeypatch.setattr(getpass, "getuser", lambda: "student2")
    second = runner_env()["MYPY_CACHE_DIR"]

    assert first != second, f"both users share {first}"
    assert runner_env()["MYPY_CACHE_DIR"] == second, "the path must be stable so the cache still helps"


def test_mypy_cache_dir_survives_an_unknown_user(monkeypatch) -> None:
    import getpass

    from pyta_lsp.scheduler import runner_env

    def no_user() -> str:
        raise OSError("no login name")

    monkeypatch.setattr(getpass, "getuser", no_user)

    assert runner_env()["MYPY_CACHE_DIR"]


def test_cancel_all_stops_checks_that_are_still_queued_for_a_slot(tmp_path: Path) -> None:
    # cancel_all only ever bumped the generation of a key that already had a
    # process, so a thread parked on the slot semaphore woke up after shutdown,
    # spawned a fresh runner and waited the full timeout on it. Exit time then
    # grew with the number of open documents.
    from pyta_lsp.scheduler import default_spawn

    spawned: list[list[str]] = []

    def counting_spawn(argv: list[str], cwd: str):
        spawned.append(argv)
        return default_spawn(argv, cwd)

    scheduler = CheckScheduler(spawn=counting_spawn, timeout=60, max_parallel=2)
    results: dict[str, object] = {}

    def run(key: str) -> None:
        results[key] = scheduler.run(
            key, _grandchild_argv(tmp_path / f"{key}.txt", sleep=20), str(tmp_path)
        )

    threads = [threading.Thread(target=run, args=(key,)) for key in ("a", "b", "c", "d")]
    for t in threads:
        t.start()
    time.sleep(1.0)

    started = time.monotonic()
    scheduler.cancel_all()
    for t in threads:
        t.join(timeout=20)
    elapsed = time.monotonic() - started

    assert not any(t.is_alive() for t in threads), "a check thread never returned"
    assert len(spawned) == 2, f"a runner was spawned after cancel_all: {len(spawned)} spawns"
    assert elapsed < 3, f"cancel_all took {elapsed:.1f}s to release every thread"
    assert set(results) == {"a", "b", "c", "d"}
    assert all(value is None for value in results.values()), results
