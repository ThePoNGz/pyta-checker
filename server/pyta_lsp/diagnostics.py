"""Convert PythonTA JSON-reporter messages into LSP diagnostics."""
from __future__ import annotations

from typing import Any, Sequence

from lsprotocol import types

from .pyta_codes import PYTA_DOCUMENTED_CODES

SOURCE = "PythonTA"
FAILURE_CODE = "pyta-error"
PYTA_DOCS = "https://www.cs.toronto.edu/~david/pyta/checkers/index.html"
PYLINT_DOCS = "https://pylint.readthedocs.io/en/stable/user_guide/messages"
_PYLINT_DIRS = {
    "F": "fatal",
    "E": "error",
    "W": "warning",
    "C": "convention",
    "R": "refactor",
    "I": "information",
}
_UNKNOWN_END_COLUMN = 10_000


def docs_url(msg_id: str, symbol: str) -> str:
    if msg_id.upper() in PYTA_DOCUMENTED_CODES:
        return f"{PYTA_DOCS}#{msg_id.lower()}"
    directory = _PYLINT_DIRS.get(msg_id[:1].upper())
    if directory and symbol:
        return f"{PYLINT_DOCS}/{directory}/{symbol.lower()}.html"
    return PYTA_DOCS


def _utf16_col(line: str, col: int) -> int:
    return len(line[:col].encode("utf-16-le")) // 2


def _line_text(lines: Sequence[str] | None, index: int) -> str | None:
    if lines is None or index < 0 or index >= len(lines):
        return None
    return lines[index].rstrip("\r\n")


def to_diagnostic(msg: dict[str, Any], lines: Sequence[str] | None) -> types.Diagnostic:
    line0 = max(int(msg.get("line") or 1) - 1, 0)
    col = max(int(msg.get("column") or 0), 0)
    start_text = _line_text(lines, line0)
    start_char = _utf16_col(start_text, col) if start_text is not None else col

    end_line_raw = msg.get("end_line")
    end_col_raw = msg.get("end_column")
    if end_line_raw is None or end_col_raw is None:
        end_line0 = line0
        if start_text is not None:
            end_char = max(_utf16_col(start_text, len(start_text)), start_char)
        else:
            end_char = _UNKNOWN_END_COLUMN
    else:
        end_line0 = max(int(end_line_raw) - 1, 0)
        end_text = _line_text(lines, end_line0)
        end_col = max(int(end_col_raw), 0)
        end_char = _utf16_col(end_text, end_col) if end_text is not None else end_col

    category = str(msg.get("category", ""))
    severity = (
        types.DiagnosticSeverity.Error
        if category in ("error", "fatal")
        else types.DiagnosticSeverity.Warning
    )
    msg_id = str(msg.get("msg_id", ""))
    symbol = str(msg.get("symbol", ""))
    text = str(msg.get("msg", ""))
    message = f"{symbol}: {text}" if symbol else text

    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=line0, character=start_char),
            end=types.Position(line=end_line0, character=end_char),
        ),
        message=message,
        severity=severity,
        code=msg_id,
        code_description=types.CodeDescription(href=docs_url(msg_id, symbol)),
        source=SOURCE,
    )


def failure_diagnostic(reason: str) -> types.Diagnostic:
    return types.Diagnostic(
        range=types.Range(start=types.Position(0, 0), end=types.Position(0, _UNKNOWN_END_COLUMN)),
        message=f"PythonTA could not check this file: {reason}",
        severity=types.DiagnosticSeverity.Error,
        code=FAILURE_CODE,
        source=SOURCE,
    )
