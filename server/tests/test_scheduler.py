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
