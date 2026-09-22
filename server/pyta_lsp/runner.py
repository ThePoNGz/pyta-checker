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
import logging
import os
import sys
import tokenize
import traceback
from pathlib import Path
from typing import Any, Mapping

from .config_extract import ExtractedConfig, extract_config
from .paths import mypy_cache_dir

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


def strip_cwd_from_path(cwd: str | None = None, path: list[str] = sys.path) -> None:
    """Drop the entry `python -m` puts at sys.path[0].

    That entry is the directory of the file being checked, so without this a
    module sitting beside a student's file (python_ta.py, queue.py, random.py)
    outranks the bundled libs and the standard library.
    """
    target = os.path.normcase(os.path.abspath(os.getcwd() if cwd is None else cwd))
    for entry in [p for p in path if os.path.normcase(os.path.abspath(p)) == target]:
        path.remove(entry)


def _read_source(path: Path) -> str:
    """Honour a PEP 263 coding cookie or BOM, the way python and pylint both do."""
    with open(path, "rb") as handle:
        encoding, _ = tokenize.detect_encoding(handle.readline)
    return path.read_text(encoding=encoding)


def _logged_error(log: str) -> str | None:
    """pyta logs the real cause with logging.error before it calls sys.exit."""
    lines = [line for line in log.splitlines() if line.startswith("[ERROR]")]
    return lines[-1][len("[ERROR]"):].strip() if lines else None


def _empty_result() -> dict[str, Any]:
    return {
        "ok": True,
        "config_source": "default",
        "messages": [],
        "log": "",
        "warnings": [],
        "elsewhere": [],
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
        "confidence": ["UNDEFINED", "Warning without any associated confidence level."],
        "line": exc.lineno or 1,
        "column": max((exc.offset or 1) - 1, 0),
        "end_line": exc.end_lineno,
        "end_column": (exc.end_offset - 1) if exc.end_offset else None,
        "line_end": exc.end_lineno,
        "column_end": (exc.end_offset - 1) if exc.end_offset else None,
        "path": str(path),
        "abspath": str(path),
        "module": path.stem,
        "obj": "",
        "snippet": "",
        "number_of_occurrences": 1,
    }


def _owns(filename: str, target: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(filename)) == os.path.normcase(str(target))
    except (OSError, ValueError):
        return False


def _split_messages(report_data: list[Any], target: Path) -> tuple[list[Any], list[Any]]:
    """Separate the checked file's messages from every other file's.

    The reporter keeps an entry per file it read and drops only the non-.py ones
    with nothing to say, so a bad option in the course config arrives here
    carrying that file's line numbers.
    """
    messages: list[Any] = []
    elsewhere: list[Any] = []
    for entry in report_data:
        msgs = entry.get("msgs", [])
        if not msgs:
            continue
        filename = entry.get("filename") or ""
        if not filename or _owns(filename, target):
            messages.extend(msgs)
            continue
        elsewhere.extend({**m, "filename": filename} for m in msgs)
    return messages, elsewhere


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
    source_dir: str | None = None,
) -> dict[str, Any]:
    result = _empty_result()
    file_path = Path(path)
    if not file_path.is_file():
        result.update(ok=False, error=f"file not found: {file_path}")
        return result
    file_path = file_path.resolve()
    # The server checks a UTF-8 copy of the editor buffer, which cannot sit beside
    # the original, so the folder that owns the file is not always its parent.
    base_dir = Path(source_dir).resolve() if source_dir else file_path.parent

    try:
        source = _read_source(file_path)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        result.update(ok=False, error=f"could not read file: {exc}")
        return result

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        result["messages"] = [_syntax_error_message(exc, file_path)]
        return result

    extracted = (
        extract_config(tree, base_dir)
        if use_embedded
        else ExtractedConfig("absent", None, False)
    )
    result["warnings"].extend(extracted.warnings)
    errors_only = errors_only or extracted.errors_only
    load_default_config = True if extracted.load_default_config is None else extracted.load_default_config
    config, pylint_args, source_kind = _resolve_config(extracted, config_path, workspace_root, base_dir)
    result["config_source"] = source_kind

    report = io.StringIO()
    log = io.StringIO()
    old_cwd = os.getcwd()
    old_cache = os.environ.get("MYPY_CACHE_DIR")
    parent_str = str(base_dir)
    inserted_path = False
    # python_ta's logging.basicConfig only binds a handler on the first call in a
    # process, so a handler attached here directly to the root logger is the only
    # way to reliably capture its log output on repeated in-process runs. Match
    # pyta's own format/level so its "[ERROR] ..." pre-check failures still carry
    # the prefix the fallback below looks for.
    root_logger = logging.getLogger()
    log_handler = logging.StreamHandler(log)
    log_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger.addHandler(log_handler)
    previous_level = root_logger.level
    if previous_level == logging.NOTSET or previous_level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    try:
        # mypy shortens only paths under its cwd, and python_ta's
        # ^(?P<file>[^:]+): cannot match a Windows drive letter, so an absolute
        # path drops every E9951-E9956 message. Any ancestor will do, and the
        # server deliberately spawns a staged check one directory above the copy
        # so that nothing of the student's sits in sys.path[0].
        if not file_path.is_relative_to(Path(old_cwd).resolve()):
            os.chdir(file_path.parent)
        # python_ta spawns mypy with this process's cwd and environment, and mypy
        # writes a .mypy_cache into that cwd unless it is told otherwise. The
        # server's spawn env pins this; a check run in process has to pin it too.
        os.environ["MYPY_CACHE_DIR"] = mypy_cache_dir()
        if parent_str not in sys.path:
            sys.path.append(parent_str)
            inserted_path = True
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            import python_ta

            result["pyta_version"] = getattr(python_ta, "__version__", "unknown")
            result["pyta_location"] = os.path.dirname(python_ta.__file__)
            checker = python_ta.check_errors if errors_only else python_ta.check_all
            # pylint_args is ours: it carries the reporter this runner parses, and
            # pyta reads the first --output-format it finds, so a student's own
            # list could silently take the output away.
            checker(
                str(file_path),
                config=config,
                output=report,
                load_default_config=load_default_config,
                pylint_args=pylint_args,
            )
    except (Exception, SystemExit) as exc:  # pyta and pylint raise many types, and both call sys.exit()
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        log_handler.flush()
        root_logger.removeHandler(log_handler)
        root_logger.setLevel(previous_level)
        if inserted_path:
            sys.path.remove(parent_str)
        os.chdir(old_cwd)
        if old_cache is None:
            os.environ.pop("MYPY_CACHE_DIR", None)
        else:
            os.environ["MYPY_CACHE_DIR"] = old_cache
    result["log"] = log.getvalue()
    if not result["ok"]:
        result["error"] = _logged_error(result["log"]) or result["error"]
        return result

    raw = report.getvalue().strip()
    if not raw:
        logged = _logged_error(result["log"])
        if logged:
            result.update(ok=False, error=logged)
        return result
    try:
        report_data = json.loads(raw)
    except json.JSONDecodeError:
        result.update(ok=False, error="PythonTA produced output that is not JSON", traceback=raw[-2000:])
        return result
    result["messages"], result["elsewhere"] = _split_messages(report_data, file_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pyta_lsp.runner")
    parser.add_argument("path")
    parser.add_argument("--config")
    parser.add_argument("--errors-only", action="store_true")
    parser.add_argument("--no-embedded-config", action="store_true")
    parser.add_argument("--workspace-root")
    parser.add_argument("--source-dir")
    args = parser.parse_args(argv)
    strip_cwd_from_path()
    apply_import_strategy()
    result = run_check(
        Path(args.path),
        config_path=args.config,
        errors_only=args.errors_only,
        use_embedded=not args.no_embedded_config,
        workspace_root=args.workspace_root,
        source_dir=args.source_dir,
    )
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
