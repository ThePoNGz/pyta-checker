import json
import os
import subprocess
import sys
from pathlib import Path

from pyta_lsp.runner import ENV_LIBS, ENV_STRATEGY, apply_import_strategy, run_check


def _codes(result: dict) -> list[str]:
    return [m["msg_id"] for m in result["messages"]]


def test_course_style_honors_embedded_config(fixtures: Path) -> None:
    result = run_check(fixtures / "course_style.py")
    assert result["ok"] is True
    assert result["config_source"] == "embedded"
    codes = _codes(result)
    assert "E9989" in codes
    assert "W0612" in codes
    assert "E9999" not in codes
    assert "E9998" not in codes
    pep8 = next(m for m in result["messages"] if m["msg_id"] == "E9989")
    assert (pep8["line"], pep8["column"]) == (12, 9)
    assert result["pyta_version"]
    assert result["pyta_location"]


def test_no_config_reports_forbidden_import_and_io(fixtures: Path) -> None:
    result = run_check(fixtures / "no_config.py")
    assert result["ok"] is True
    assert result["config_source"] == "default"
    codes = _codes(result)
    assert "E9999" in codes
    assert "E9998" in codes


def test_string_config_path_is_used(fixtures: Path) -> None:
    result = run_check(fixtures / "string_config.py")
    assert result["ok"] is True
    assert result["config_source"] == "embedded"
    assert "E9999" not in _codes(result)
    assert "Using config file" in result["log"]


def test_check_errors_style_runs(fixtures: Path) -> None:
    result = run_check(fixtures / "check_errors_style.py")
    assert result["ok"] is True
    assert result["config_source"] == "embedded"


def test_nonliteral_config_warns_and_uses_defaults(fixtures: Path) -> None:
    result = run_check(fixtures / "nonliteral_config.py")
    assert result["ok"] is True
    assert result["config_source"] == "default"
    assert any("not a literal" in w for w in result["warnings"])


def test_syntax_error_yields_e0001_without_running_pyta(fixtures: Path) -> None:
    result = run_check(fixtures / "syntax_error.py")
    assert result["ok"] is True
    assert _codes(result) == ["E0001"]
    msg = result["messages"][0]
    assert msg["symbol"] == "syntax-error"
    assert msg["category"] == "error"
    assert msg["line"] == 4
    assert result["pyta_version"] is None


def test_clean_file_has_no_messages(fixtures: Path) -> None:
    result = run_check(fixtures / "clean.py")
    assert result["ok"] is True
    assert result["messages"] == []


def test_explicit_config_path_applies_when_no_embedded_config(fixtures: Path) -> None:
    result = run_check(fixtures / "no_config.py", config_path="pyta_config.txt", workspace_root=str(fixtures))
    assert result["ok"] is True
    assert result["config_source"] == "file"
    # pyta_config.txt allows random but not datetime, so any E9999 left must be about datetime.
    assert all("datetime" in m["msg"] for m in result["messages"] if m["msg_id"] == "E9999")


def test_missing_file_is_a_failure() -> None:
    result = run_check(Path("definitely_missing_file.py"))
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_cli_prints_only_json(fixtures: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pyta_lsp.runner", str(fixtures / "course_style.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=str(fixtures),
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert "E9989" in [m["msg_id"] for m in data["messages"]]


def test_apply_import_strategy_moves_libs_to_end(tmp_path: Path) -> None:
    libs = str(tmp_path)
    path = ["first", libs, "second"]
    apply_import_strategy({ENV_LIBS: libs, ENV_STRATEGY: "fromEnvironment"}, path)
    assert path == ["first", "second", libs]


def test_apply_import_strategy_noop_when_bundled(tmp_path: Path) -> None:
    libs = str(tmp_path)
    path = [libs, "second"]
    apply_import_strategy({ENV_LIBS: libs, ENV_STRATEGY: "useBundled"}, path)
    assert path == [libs, "second"]


def test_log_captures_logging_output_across_repeated_calls(fixtures: Path, monkeypatch) -> None:
    import logging
    import sys
    import types

    def fake_check_all(path, config=None, output=None, pylint_args=None):
        logging.getLogger("python_ta.fake").warning("logged by pyta")
        output.write("[]")

    fake = types.ModuleType("python_ta")
    fake.__version__ = "0.0-fake"
    fake.__file__ = str(fixtures / "python_ta.py")
    fake.check_all = fake_check_all
    fake.check_errors = fake_check_all
    monkeypatch.setitem(sys.modules, "python_ta", fake)

    first = run_check(fixtures / "clean.py")
    second = run_check(fixtures / "clean.py")
    assert first["ok"] and second["ok"]
    assert "logged by pyta" in first["log"]
    assert "logged by pyta" in second["log"]


def test_sys_path_is_restored_after_check(fixtures: Path) -> None:
    import sys

    before = list(sys.path)
    run_check(fixtures / "clean.py")
    assert sys.path == before


def test_syntax_error_message_carries_full_key_set(fixtures: Path) -> None:
    msg = run_check(fixtures / "syntax_error.py")["messages"][0]
    for key in ("abspath", "confidence", "line_end", "column_end"):
        assert key in msg
