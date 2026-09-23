"""Convert PythonTA JSON-reporter messages into LSP diagnostics."""
from __future__ import annotations

import os
import re
from typing import Any, Sequence

from lsprotocol import types

from .pyta_codes import PYTA_DOCUMENTED_CODES

SOURCE = "PythonTA"
FAILURE_CODE = "pyta-error"
CONFIG_WARNING_CODE = "pyta-config"
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
# Anything routed through an astroid node carries a UTF-8 byte offset. These do
# not, and they arrive mixed into the same message list. E9989 comes from
# pycodestyle, E0001 from SyntaxError.offset, C0303 is len() of the stripped
# line, W0511 is a tokenize column, and W1401/W1402 index into the string body.
# All of those count characters.
_CHARACTER_BASED_CODES = frozenset({"E9989", "E0001", "C0303", "W0511", "W1401", "W1402"})
# A third convention: E995x come from mypy through the python_ta static type
# checker, which forwards the mypy columns unchanged. They are UTF-8 byte offsets
# like the astroid ones, but the start is 1-based. The end column is 1-based
# inclusive, which is already the 0-based exclusive offset used everywhere else,
# so we only shift the start back.
_ONE_BASED_START_CODES = frozenset({"E9951", "E9952", "E9953", "E9954", "E9955", "E9956"})


_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)")


def split_lines(source: str) -> list[str]:
    """Split source into lines, keepends, on \\r\\n, \\r and \\n only.

    str.splitlines also breaks on \\x0c, \\x0b, \\x1c-\\x1e, \\x85, \\u2028 and
    \\u2029. Neither the Python tokenizer nor the editor counts any of those as
    a line, so one inside a comment shifts every later message onto the wrong line.
    """
    lines = _LINE_RE.findall(source)
    consumed = sum(len(line) for line in lines)
    if consumed < len(source):
        lines.append(source[consumed:])
    return lines


def docs_url(msg_id: str, symbol: str) -> str:
    """The docs page for a message, the PyTA one when it has an anchor there, else pylint."""
    if msg_id.upper() in PYTA_DOCUMENTED_CODES:
        return f"{PYTA_DOCS}#{msg_id.lower()}"
    directory = _PYLINT_DIRS.get(msg_id[:1].upper())
    if directory and symbol:
        return f"{PYLINT_DOCS}/{directory}/{symbol.lower()}.html"
    return PYTA_DOCS


def _utf16_col(line: str, col: int) -> int:
    return len(line[:col].encode("utf-16-le")) // 2


def _byte_to_char(line: str, byte_col: int) -> int:
    """astroid/pylint report col_offset as a UTF-8 byte offset, not a character index."""
    raw = line.encode("utf-8")
    if byte_col >= len(raw):
        return len(line)
    return len(raw[:byte_col].decode("utf-8", errors="ignore"))


def _source_col(line: str | None, col: int, byte_based: bool) -> int:
    if line is None or not byte_based:
        return col
    return _byte_to_char(line, col)


def _line_text(lines: Sequence[str] | None, index: int) -> str | None:
    if lines is None or index < 0 or index >= len(lines):
        return None
    return lines[index].rstrip("\r\n")


def to_diagnostic(msg: dict[str, Any], lines: Sequence[str] | None) -> types.Diagnostic:
    """Turn one PythonTA message into a diagnostic the editor can place.

    Args:
        msg: one message from the pyta JSON reporter.
        lines: the checked text split with keepends, used to turn the reported column
            into the UTF-16 one LSP wants. None means we pass the column through.

    Returns:
        A diagnostic with a range, a severity and a link to the docs for that code.
    """
    msg_id = str(msg.get("msg_id", ""))
    byte_based = msg_id.upper() not in _CHARACTER_BASED_CODES
    line0 = max(int(msg.get("line") or 1) - 1, 0)
    col = max(int(msg.get("column") or 0), 0)
    if msg_id.upper() in _ONE_BASED_START_CODES:
        col = max(col - 1, 0)
    start_text = _line_text(lines, line0)
    start_char = (
        _utf16_col(start_text, _source_col(start_text, col, byte_based))
        if start_text is not None
        else col
    )

    end_line_raw = msg.get("end_line")
    end_col_raw = msg.get("end_column")
    if end_col_raw is None:
        # No end column: end of the relevant line (start line if end_line is
        # also missing, otherwise the given end_line).
        end_line0 = line0 if end_line_raw is None else max(int(end_line_raw) - 1, 0)
        end_text = _line_text(lines, end_line0)
        end_char = _utf16_col(end_text, len(end_text)) if end_text is not None else _UNKNOWN_END_COLUMN
    elif end_line_raw is None:
        # End column given without an end line: stays on the start line.
        end_line0 = line0
        end_col = max(int(end_col_raw), 0)
        end_char = (
            _utf16_col(start_text, _source_col(start_text, end_col, byte_based))
            if start_text is not None
            else end_col
        )
    else:
        end_line0 = max(int(end_line_raw) - 1, 0)
        end_text = _line_text(lines, end_line0)
        end_col = max(int(end_col_raw), 0)
        end_char = (
            _utf16_col(end_text, _source_col(end_text, end_col, byte_based))
            if end_text is not None
            else end_col
        )

    if end_line0 == line0:
        end_char = max(end_char, start_char)

    category = str(msg.get("category", ""))
    severity = (
        types.DiagnosticSeverity.Error
        if category in ("error", "fatal")
        else types.DiagnosticSeverity.Warning
    )
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


def config_diagnostic(msg: dict[str, Any]) -> types.Diagnostic:
    """PythonTA will warn the user thru the config file instead of the code file the user is opening"""
    msg_id = str(msg.get("msg_id", ""))
    symbol = str(msg.get("symbol", ""))
    name = os.path.basename(str(msg.get("filename", ""))) or "config"
    where = f"{name}, line {msg['line']}" if msg.get("line") else name
    return types.Diagnostic(
        range=types.Range(start=types.Position(0, 0), end=types.Position(0, _UNKNOWN_END_COLUMN)),
        message=f"PythonTA config {where}: {msg_id} ({symbol}) {msg.get('msg', '')}".rstrip(),
        severity=types.DiagnosticSeverity.Information,
        code=msg_id,
        code_description=types.CodeDescription(href=docs_url(msg_id, symbol)),
        source=SOURCE,
    )


def config_warning_diagnostic(message: str) -> types.Diagnostic:
    """A warning that came out of reading the check_all call in the file.

    Every warning the runner returns comes from that reading, and each one means
    the file was checked against something other than the config the call asks
    for. Sitting in the Output log alone it would be invisible.
    """
    return types.Diagnostic(
        range=types.Range(start=types.Position(0, 0), end=types.Position(0, _UNKNOWN_END_COLUMN)),
        message=f"PythonTA config: {message}",
        severity=types.DiagnosticSeverity.Information,
        code=CONFIG_WARNING_CODE,
        source=SOURCE,
    )


def failure_diagnostic(reason: str) -> types.Diagnostic:
    """Says the check could not run at all, with whatever reason we have."""
    return types.Diagnostic(
        range=types.Range(start=types.Position(0, 0), end=types.Position(0, _UNKNOWN_END_COLUMN)),
        message=f"PythonTA could not check this file: {reason}",
        severity=types.DiagnosticSeverity.Error,
        code=FAILURE_CODE,
        source=SOURCE,
    )
