"""Check one file with PythonTA and print a JSON result on stdout.

Usage: python -m pyta_lsp.runner <file> [--config PATH] [--errors-only]
                                        [--no-embedded-config] [--workspace-root DIR]
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Mapping

from .config_extract import ExtractedConfig, extract_config

JSON_FORMAT = {"output-format": "pyta-json"}
JSON_PYLINT_ARGS = ["--output-format", "pyta-json"]
ENV_LIBS = "PYTA_LSP_LIBS"
ENV_STRATEGY = "PYTA_LSP_IMPORT_STRATEGY"


def apply_import_strategy(env: Mapping[str, str] = os.environ, path: list[str] = sys.path) -> None:
    """With fromEnvironment, demote the bundled libs so an installed python_ta wins."""
    libs = env.get(ENV_LIBS)
    if not libs or env.get(ENV_STRATEGY) != "fromEnvironment":
        return
    target = os.path.normcase(os.path.abspath(libs))
    for entry in [p for p in path if os.path.normcase(os.path.abspath(p)) == target]:
        path.remove(entry)
    path.append(libs)


def _empty_result() -> dict[str, Any]:
    return {
        "ok": True,
        "config_source": "default",
        "messages": [],
        "log": "",
        "warnings": [],
        "error": None,
        "traceback": None,
        "pyta_version": None,
        "pyta_location": None,
    }


def _syntax_error_message(exc: SyntaxError, path: Path) -> dict[str, Any]:
    return {
        "msg_id": "E0001",
        "symbol": "syntax-error",
        "msg": exc.msg or "invalid syntax",
        "C": "E",
        "category": "error",
        "line": exc.lineno or 1,
        "column": max((exc.offset or 1) - 1, 0),
        "end_line": exc.end_lineno,
        "end_column": (exc.end_offset - 1) if exc.end_offset else None,
        "path": str(path),
        "module": path.stem,
        "obj": "",
        "snippet": "",
        "number_of_occurrences": 1,
    }


def _resolve_config(
    extracted: ExtractedConfig, config_path: str | None, workspace_root: str | None, file_dir: Path
) -> tuple[dict[str, Any] | str, list[str] | None, str]:
    if extracted.kind == "dict":
        return {**extracted.value, **JSON_FORMAT}, None, "embedded"
    if extracted.kind == "path":
        return extracted.value, JSON_PYLINT_ARGS, "embedded"
    if config_path:
        cfg = Path(config_path)
        if not cfg.is_absolute():
            cfg = (Path(workspace_root) if workspace_root else file_dir) / cfg
        return str(cfg), JSON_PYLINT_ARGS, "file"
    return dict(JSON_FORMAT), None, "default"


def run_check(
    path: Path,
    *,
    config_path: str | None = None,
    errors_only: bool = False,
    use_embedded: bool = True,
    workspace_root: str | None = None,
) -> dict[str, Any]:
    result = _empty_result()
    file_path = Path(path)
    if not file_path.is_file():
        result.update(ok=False, error=f"file not found: {file_path}")
        return result
    file_path = file_path.resolve()

    try:
        source = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        result.update(ok=False, error=f"could not read file: {exc}")
        return result

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        result["messages"] = [_syntax_error_message(exc, file_path)]
        return result

    extracted = (
        extract_config(tree, file_path.parent)
        if use_embedded
        else ExtractedConfig("absent", None, False)
    )
    result["warnings"].extend(extracted.warnings)
    errors_only = errors_only or extracted.errors_only
    config, pylint_args, source_kind = _resolve_config(extracted, config_path, workspace_root, file_path.parent)
    result["config_source"] = source_kind

    report = io.StringIO()
    log = io.StringIO()
    old_cwd = os.getcwd()
    try:
        os.chdir(file_path.parent)
        if str(file_path.parent) not in sys.path:
            sys.path.insert(0, str(file_path.parent))
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            import python_ta

            result["pyta_version"] = getattr(python_ta, "__version__", "unknown")
            result["pyta_location"] = os.path.dirname(python_ta.__file__)
            checker = python_ta.check_errors if errors_only else python_ta.check_all
            checker(str(file_path), config=config, output=report, pylint_args=pylint_args)
    except Exception as exc:  # pyta and pylint raise many types; report all of them
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        os.chdir(old_cwd)
    result["log"] = log.getvalue()
    if not result["ok"]:
        return result

    raw = report.getvalue().strip()
    if not raw:
        error_lines = [line for line in result["log"].splitlines() if line.startswith("[ERROR]")]
        if error_lines:
            result.update(ok=False, error=error_lines[-1][len("[ERROR]"):].strip())
        return result
    try:
        report_data = json.loads(raw)
    except json.JSONDecodeError:
        result.update(ok=False, error="PythonTA produced output that is not JSON", traceback=raw[-2000:])
        return result
    result["messages"] = [m for entry in report_data for m in entry.get("msgs", [])]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pyta_lsp.runner")
    parser.add_argument("path")
    parser.add_argument("--config")
    parser.add_argument("--errors-only", action="store_true")
    parser.add_argument("--no-embedded-config", action="store_true")
    parser.add_argument("--workspace-root")
    args = parser.parse_args(argv)
    apply_import_strategy()
    result = run_check(
        Path(args.path),
        config_path=args.config,
        errors_only=args.errors_only,
        use_embedded=not args.no_embedded_config,
        workspace_root=args.workspace_root,
    )
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
