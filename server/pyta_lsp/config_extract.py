"""Find the PythonTA config embedded in a file's check_all/check_errors call."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CHECK_FUNCTIONS = ("check_all", "check_errors")


@dataclass
class ExtractedConfig:
    kind: Literal["dict", "path", "absent"]
    value: dict[str, Any] | str | None
    errors_only: bool
    warnings: list[str] = field(default_factory=list)
    # None means the call said nothing, so pyta's own default stands.
    load_default_config: bool | None = None


def _pyta_bindings(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """The names in this file that really refer to python_ta.

    The course pattern imports it inside the __main__ block, so this walks the
    whole tree rather than the top level.
    """
    modules: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "python_ta" or alias.name.startswith("python_ta."):
                    modules.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] != "python_ta":
                continue
            for alias in node.names:
                if alias.name in CHECK_FUNCTIONS:
                    functions[alias.asname or alias.name] = alias.name
    return modules, functions


def _callee_name(call: ast.Call, modules: set[str], functions: dict[str, str]) -> str | None:
    """The check function this call invokes, or None if it is not python_ta's.

    A student helper named check_all is not pyta's, and letting one supply the
    config lints them against settings the grader never applies.
    """
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr in CHECK_FUNCTIONS and isinstance(func.value, ast.Name) and func.value.id in modules:
            return func.attr
        return None
    if isinstance(func, ast.Name):
        return functions.get(func.id)
    return None


def _check_calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    modules, functions = _pyta_bindings(tree)
    calls = [
        (name, node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _callee_name(node, modules, functions))
    ]
    calls.sort(key=lambda item: (item[1].lineno, item[1].col_offset))
    return calls


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((kw for kw in call.keywords if kw.arg == name), None)


def _load_default_config(call: ast.Call, name: str) -> tuple[bool | None, list[str]]:
    """A literal load_default_config, or None when the call did not pin it down.

    A course file that turns the defaults off is otherwise checked against them
    merged in, which is not what the grader runs.
    """
    kw = _keyword(call, "load_default_config")
    if kw is None:
        return None, []
    try:
        value = ast.literal_eval(kw.value)
    except (ValueError, SyntaxError, TypeError):
        value = None
    if isinstance(value, bool):
        return value, []
    return None, [
        f"line {call.lineno}: load_default_config argument to {name}() is not a literal bool; ignoring it"
    ]


def extract_config(tree: ast.AST, base_dir: Path) -> ExtractedConfig:
    calls = _check_calls(tree)
    if not calls:
        return ExtractedConfig("absent", None, False)

    # The call that supplies the config is the one whose other arguments apply.
    name, call = next(
        ((n, c) for n, c in calls if _keyword(c, "config") is not None), calls[0]
    )
    load_default, warnings = _load_default_config(call, name)
    config_kw = _keyword(call, "config")
    if config_kw is None:
        errors_only = calls[0][0] == "check_errors"
        return ExtractedConfig("absent", None, errors_only, warnings, load_default)

    errors_only = name == "check_errors"
    try:
        value = ast.literal_eval(config_kw.value)
    except (ValueError, SyntaxError, TypeError):
        return ExtractedConfig(
            "absent",
            None,
            errors_only,
            warnings + [f"line {call.lineno}: config argument to {name}() is not a literal; using defaults"],
            load_default,
        )
    if isinstance(value, dict):
        return ExtractedConfig("dict", value, errors_only, warnings, load_default)
    if isinstance(value, str):
        path = Path(value)
        if not path.is_absolute():
            path = base_dir / path
        return ExtractedConfig("path", str(path), errors_only, warnings, load_default)
    return ExtractedConfig(
        "absent",
        None,
        errors_only,
        warnings
        + [f"line {call.lineno}: config argument to {name}() is neither a dict nor a string; using defaults"],
        load_default,
    )
