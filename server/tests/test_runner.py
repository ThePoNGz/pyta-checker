import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

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

    def fake_check_all(path, config=None, output=None, load_default_config=True, pylint_args=None):
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


def test_sys_path_is_restored_after_check(fixtures: Path, monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "path", list(sys.path))
    before = list(sys.path)
    run_check(fixtures / "clean.py")
    assert sys.path == before


def test_syntax_error_message_carries_full_key_set(fixtures: Path) -> None:
    msg = run_check(fixtures / "syntax_error.py")["messages"][0]
    for key in ("abspath", "confidence", "line_end", "column_end"):
        assert key in msg


def test_pyta_precheck_failure_is_reported_as_error(fixtures: Path) -> None:
    result = run_check(fixtures / "pylint_comment.py")
    assert result["ok"] is False
    assert "pylint:" in result["error"]
    assert "[ERROR]" in result["log"]


def _run_cli(cwd: Path, target: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pyta_lsp.runner", target, *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=str(cwd),
    )


def test_module_beside_the_file_cannot_shadow_python_ta(tmp_path: Path) -> None:
    (tmp_path / "python_ta.py").write_text(
        "import pathlib\n"
        "pathlib.Path(__file__).with_name('SHADOW_RAN.txt').write_text('ran')\n"
        "def check_all(*args, **kwargs):\n"
        "    return None\n",
        encoding="utf-8",
    )
    (tmp_path / "a1.py").write_text('"""Doc."""\nx = 1\n', encoding="utf-8")

    _run_cli(tmp_path, "a1.py")

    assert not (tmp_path / "SHADOW_RAN.txt").exists()


def test_stdlib_named_module_beside_the_file_does_not_break_checking(tmp_path: Path) -> None:
    (tmp_path / "queue.py").write_text(
        '"""A course Queue ADT."""\n\n\nclass Queue:\n    """A FIFO queue."""\n',
        encoding="utf-8",
    )
    (tmp_path / "a1.py").write_text('"""Doc."""\nx = 1\n', encoding="utf-8")

    proc = _run_cli(tmp_path, "a1.py")

    data = json.loads(proc.stdout)
    assert data["ok"] is True, data["error"]


def test_missing_config_file_reports_the_underlying_error(tmp_path: Path) -> None:
    (tmp_path / "a1.py").write_text(
        '"""Doc."""\n'
        "x = 1\n\n"
        "if __name__ == '__main__':\n"
        "    import python_ta\n"
        "    python_ta.check_all(config='no_such_config.txt')\n",
        encoding="utf-8",
    )

    proc = _run_cli(tmp_path, "a1.py")

    assert proc.returncode == 0, f"runner died instead of reporting: rc={proc.returncode}"
    data = json.loads(proc.stdout)
    assert data["ok"] is False
    assert "no_such_config.txt" in (data["error"] or "")


def test_non_utf8_coding_cookie_is_decoded_for_parsing(tmp_path: Path) -> None:
    # PEP 263. python and pylint both honour this cookie so the runner does too, the
    # file decodes and a syntax error in it is reported as E0001 rather than as an
    # unreadable file. PythonTA itself still cannot check such a file, because
    # upstream reads it as UTF-8 and raises, so this covers the parse step only.
    source = '# -*- coding: cp1252 -*-\n"""Doc."""\nX = "café" ** ** 2\n'
    (tmp_path / "a1.py").write_bytes(source.encode("cp1252"))

    proc = _run_cli(tmp_path, "a1.py")

    data = json.loads(proc.stdout)
    assert [m["msg_id"] for m in data["messages"]] == ["E0001"]


def _staged_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A file staged outside its own folder, with a sibling module left behind."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "helper.py").write_text('"""Helper."""\n\n\ndef hi() -> int:\n    """Doc."""\n    return 1\n', encoding="utf-8")
    staged = tmp_path / "staged"
    staged.mkdir()
    target = staged / "a1.py"
    target.write_text('"""Doc."""\nimport helper\n\nX = helper.hi()\n', encoding="utf-8")
    return target, work


def test_source_dir_keeps_sibling_imports_resolvable_for_a_staged_copy(tmp_path: Path) -> None:
    # The server checks a UTF-8 copy of the editor buffer, which cannot live beside
    # the original, so imports have to resolve against the original folder. Run
    # through the CLI: astroid caches a failed module lookup for the life of the
    # process, and each real check is its own process.
    target, work = _staged_pair(tmp_path)

    without = json.loads(_run_cli(tmp_path, str(target)).stdout)
    with_dir = json.loads(_run_cli(tmp_path, str(target), "--source-dir", str(work)).stdout)

    assert "E0401" in _codes(without)
    assert "E0401" not in _codes(with_dir)


def _course_file(tmp_path: Path, name: str, extra: str) -> Path:
    path = tmp_path / name
    path.write_text(
        '"""Doc."""\nbadName = 1\nprint(badName)\n\n'
        'if __name__ == "__main__":\n'
        "    import python_ta\n"
        f'    python_ta.check_all(config="course.txt"{extra})\n',
        encoding="utf-8",
    )
    return path


def test_load_default_config_false_is_forwarded_to_pyta(tmp_path: Path) -> None:
    # The PythonTA defaults disable C0103 in favour of C9103. A course file that
    # turns the defaults off gets C0103 when it runs the check itself, so the server
    # has to turn them off too or the squiggles differ from what the grader sees.
    (tmp_path / "course.txt").write_text("[FORMAT]\nmax-line-length=100\n", encoding="utf-8")

    merged = run_check(_course_file(tmp_path, "merged.py", ""))
    own = run_check(_course_file(tmp_path, "own.py", ", load_default_config=False"))

    assert merged["ok"] is True, merged["error"]
    assert own["ok"] is True, own["error"]
    assert "C0103" not in _codes(merged)
    assert "C0103" in _codes(own), "the defaults were merged in anyway"


def test_a_message_about_the_config_file_is_not_pinned_on_the_checked_file(tmp_path: Path) -> None:
    # The PythonTA reporter keeps one entry per file it saw and drops only the
    # non-.py ones with no messages, so a bad option in the course config arrives
    # in the same list carrying the line numbers of cfg.txt.
    (tmp_path / "cfg.txt").write_text(
        "[MESSAGES CONTROL]\ndisable=not-a-real-message\n", encoding="utf-8"
    )
    (tmp_path / "a1.py").write_text(
        '"""Doc."""\nX = 1\n\nif __name__ == "__main__":\n'
        '    import python_ta\n    python_ta.check_all(config="cfg.txt")\n',
        encoding="utf-8",
    )

    result = run_check(tmp_path / "a1.py")

    assert result["ok"] is True, result["error"]
    strays = [m for m in result["messages"] if "cfg.txt" in str(m.get("path"))]
    assert strays == [], f"messages from another file were attributed here: {strays}"
    elsewhere = result["elsewhere"]
    assert [m["msg_id"] for m in elsewhere] == ["W0012"], elsewhere
    assert elsewhere[0]["filename"].endswith("cfg.txt")


def test_source_dir_resolves_an_embedded_relative_config(tmp_path: Path) -> None:
    target, work = _staged_pair(tmp_path)
    (work / "course.txt").write_text("[FORMAT]\nmax-line-length=100\n", encoding="utf-8")
    target.write_text(
        '"""Doc."""\nX = 1\n\nif __name__ == "__main__":\n'
        '    import python_ta\n    python_ta.check_all(config="course.txt")\n',
        encoding="utf-8",
    )

    result = run_check(target, source_dir=str(work))

    assert result["config_source"] == "embedded"
    assert result["ok"] is True, result["error"]


_SIBLING_MARKER = "with open(__file__ + '.MARKER', 'w') as handle:\n    handle.write('ran')\n"


def _spawn_like_the_server(source_dir: Path, name: str) -> subprocess.CompletedProcess:
    """Spawn the runner the way the server does, from an empty directory, with the
    student folder passed as --source-dir rather than used as the cwd."""
    from pyta_lsp.scheduler import runner_env

    spawn_dir = tempfile.mkdtemp(prefix="pyta-lsp-test-")
    try:
        return subprocess.run(
            [sys.executable, "-m", "pyta_lsp.runner", str(source_dir / name), "--source-dir", str(source_dir)],
            capture_output=True,
            text=True,
            env=runner_env(),
            cwd=spawn_dir,
        )
    finally:
        shutil.rmtree(spawn_dir, ignore_errors=True)


def test_a_sibling_named_after_a_stdlib_module_is_not_imported_at_startup(tmp_path: Path) -> None:
    # python -m puts the spawn directory at sys.path[0] before the runner runs any
    # module level import, and strip_cwd_from_path only runs inside main(). So the
    # server never spawns in the student folder, and on 3.11+ PYTHONSAFEPATH covers
    # the same ground.
    (tmp_path / "string.py").write_text(_SIBLING_MARKER, encoding="utf-8")
    (tmp_path / "a1.py").write_text('"""Doc."""\nX = 1\n', encoding="utf-8")

    proc = _spawn_like_the_server(tmp_path, "a1.py")

    assert not (tmp_path / "string.py.MARKER").exists(), "the student's module was executed"
    data = json.loads(proc.stdout)
    assert data["ok"] is True, data["error"]


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="an in-place check on 3.10 runs mypy in the student's folder: the residual recorded in DEVLOG 15",
)
def test_a_sibling_random_module_is_not_imported_by_the_mypy_subprocess(tmp_path: Path) -> None:
    # The python_ta StaticTypeChecker spawns `python -m mypy` with the runner cwd,
    # and mypy imports tempfile at startup, which imports random. The file is
    # checked in place here, so the runner chdirs into the student folder and only
    # PYTHONSAFEPATH keeps random.py out of that mypy.
    (tmp_path / "random.py").write_text(_SIBLING_MARKER, encoding="utf-8")
    (tmp_path / "a1.py").write_text('"""Doc."""\nCOUNT: int = 1\n', encoding="utf-8")

    proc = _spawn_like_the_server(tmp_path, "a1.py")

    assert not (tmp_path / "random.py.MARKER").exists(), "the student's module was executed"
    data = json.loads(proc.stdout)
    assert data["ok"] is True, data["error"]


def test_mypy_messages_survive_a_staged_check(tmp_path: Path) -> None:
    # The python_ta StaticTypeChecker matches mypy output with ^(?P<file>[^:]+):,
    # which a Windows drive letter cannot satisfy. mypy only shortens paths under
    # its cwd, so checking a staged copy from the source directory dropped every
    # E9951-E9956 message without a word.
    work = tmp_path / "work"
    work.mkdir()
    staged = tmp_path / "staged"
    staged.mkdir()
    target = staged / "a1.py"
    target.write_text('"""Doc."""\nCOUNT: int = "many"\n', encoding="utf-8")

    result = run_check(target, source_dir=str(work))

    assert result["ok"] is True, result["error"]
    assert "E9952" in _codes(result), _codes(result)


def test_the_runner_stays_in_a_cwd_that_already_holds_the_file(tmp_path: Path, monkeypatch) -> None:
    # The server spawns a staged check one directory above the copy so that nothing
    # of the student sits in sys.path[0]. mypy only needs a cwd the file is under,
    # so descending into the directory of the copy would give that protection away
    # for nothing.
    staged = tmp_path / "staged"
    staged.mkdir()
    target = staged / "a1.py"
    target.write_text('"""Doc."""\nCOUNT: int = "many"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    visited: list[str] = []
    real_chdir = os.chdir
    monkeypatch.setattr(os, "chdir", lambda path: visited.append(str(path)) or real_chdir(path))

    result = run_check(target, source_dir=str(tmp_path))

    assert visited == [os.getcwd()], f"the runner moved to {visited}"
    assert result["ok"] is True, result["error"]
    assert "E9952" in _codes(result), _codes(result)


def test_an_in_process_check_leaves_no_mypy_cache_in_the_cwd(tmp_path: Path, monkeypatch) -> None:
    # Only the spawn env of the server pinned MYPY_CACHE_DIR, so a check run in this
    # process, the tests or `python -m pyta_lsp.runner` by hand, dropped a
    # .mypy_cache wherever it happened to be standing. One of those got packaged
    # into the VSIX from the repository root.
    monkeypatch.delenv("MYPY_CACHE_DIR", raising=False)
    target = tmp_path / "a1.py"
    target.write_text('"""Doc."""\nCOUNT: int = "many"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = run_check(target)

    assert result["ok"] is True, result["error"]
    assert "E9952" in _codes(result), f"mypy never ran, so nothing is proven: {_codes(result)}"
    assert not (tmp_path / ".mypy_cache").exists(), sorted(p.name for p in tmp_path.iterdir())
