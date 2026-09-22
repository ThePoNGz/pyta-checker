import sys
import threading
import time
from pathlib import Path

from pyta_lsp.scheduler import CheckScheduler


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
    scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    calls: list[str] = []
    assert scheduler.guard("doc", lambda: calls.append("published")) is True
    assert calls == ["published"]


def test_guard_skips_action_after_cancel(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    scheduler.cancel("doc")
    calls: list[str] = []
    assert scheduler.guard("doc", lambda: calls.append("published")) is False
    assert calls == []


def test_guard_skips_action_for_unknown_key() -> None:
    assert CheckScheduler(timeout=30).guard("never-run", lambda: None) is False


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
    assert env["MYPY_CACHE_DIR"].endswith("pyta-checker-mypy-cache")
