from lsprotocol import types

from pyta_lsp.diagnostics import FAILURE_CODE, SOURCE, docs_url, failure_diagnostic, to_diagnostic


def _msg(**overrides):
    base = {
        "msg_id": "W0612",
        "symbol": "unused-variable",
        "msg": "The variable i is unused",
        "C": "W",
        "category": "warning",
        "line": 13,
        "column": 8,
        "end_line": 13,
        "end_column": 9,
    }
    base.update(overrides)
    return base


LINES = ["x = 1\n"] * 12 + ["    for i in range(n):\n", "    total=0\n"]


def test_maps_positions_and_fields() -> None:
    d = to_diagnostic(_msg(), LINES)
    assert d.range == types.Range(start=types.Position(12, 8), end=types.Position(12, 9))
    assert d.severity == types.DiagnosticSeverity.Warning
    assert d.code == "W0612"
    assert d.source == SOURCE
    assert d.message == "unused-variable: The variable i is unused"
    assert d.code_description is not None
    # W0612 (unused-variable) is documented on the PythonTA checkers page as of
    # 2026-09-22, so it resolves to the PyTA anchor rather than the pylint docs
    # fallback; the fallback branch is covered by test_docs_url_rules below.
    assert d.code_description.href == "https://www.cs.toronto.edu/~david/pyta/checkers/index.html#w0612"


def test_error_category_is_error_severity() -> None:
    d = to_diagnostic(_msg(msg_id="E9998", symbol="forbidden-IO-function", category="error"), LINES)
    assert d.severity == types.DiagnosticSeverity.Error
    assert d.code_description.href == "https://www.cs.toronto.edu/~david/pyta/checkers/index.html#e9998"


def test_fatal_category_is_error_severity() -> None:
    d = to_diagnostic(_msg(msg_id="F0002", symbol="astroid-error", category="fatal"), LINES)
    assert d.severity == types.DiagnosticSeverity.Error


def test_null_end_extends_to_end_of_line() -> None:
    d = to_diagnostic(_msg(msg_id="E9989", symbol="pep8-errors", category="error", line=14, column=9, end_line=None, end_column=None), LINES)
    assert d.range.start == types.Position(13, 9)
    assert d.range.end == types.Position(13, len("    total=0"))


def test_null_end_without_lines_uses_large_column() -> None:
    d = to_diagnostic(_msg(line=14, column=9, end_line=None, end_column=None), None)
    assert d.range.end.line == 13
    assert d.range.end.character >= 1000


def test_end_line_without_end_column_extends_to_end_of_that_line() -> None:
    lines = ["def f(\n", "    x=1\n", "):\n"]
    d = to_diagnostic(_msg(line=1, column=4, end_line=2, end_column=None), lines)
    assert d.range.start == types.Position(0, 4)
    assert d.range.end == types.Position(1, len("    x=1"))


def test_end_column_without_end_line_stays_on_start_line() -> None:
    lines = ["    total=0\n"]
    d = to_diagnostic(_msg(line=1, column=4, end_line=None, end_column=9), lines)
    assert d.range.start == types.Position(0, 4)
    assert d.range.end == types.Position(0, 9)


def test_columns_are_utf16_units() -> None:
    lines = ["s = '😀😀'; y=1\n"]
    # pylint reports UTF-8 byte offsets: "y" is byte 16, character 10, UTF-16 unit 12.
    d = to_diagnostic(_msg(line=1, column=16, end_line=1, end_column=17), lines)
    assert d.range.start.character == 12
    assert d.range.end.character == 13


def test_docs_url_rules() -> None:
    assert docs_url("E9989", "pep8-errors") == "https://www.cs.toronto.edu/~david/pyta/checkers/index.html#e9989"
    assert docs_url("C0114", "missing-module-docstring") == "https://pylint.readthedocs.io/en/stable/user_guide/messages/convention/missing-module-docstring.html"
    assert docs_url("I0010", "bad-inline-option") == "https://pylint.readthedocs.io/en/stable/user_guide/messages/information/bad-inline-option.html"
    assert docs_url("X0000", "") == "https://www.cs.toronto.edu/~david/pyta/checkers/index.html"


def test_failure_diagnostic() -> None:
    d = failure_diagnostic("boom")
    assert d.range.start == types.Position(0, 0)
    assert d.severity == types.DiagnosticSeverity.Error
    assert d.code == FAILURE_CODE
    assert d.source == SOURCE
    assert d.message == "PythonTA could not check this file: boom"


# Two non-ASCII characters before the reported column, so a byte offset and a
# character offset disagree by exactly 2.
_ACCENTED = 'CONSTANT = "café naïve"; badName = 1\n'
_ACCENTED_PEP8 = 'X = "café naïve";Y=1\n'


def test_pylint_columns_are_utf8_byte_offsets() -> None:
    # badName starts at character 25; pylint reports byte offset 27.
    d = to_diagnostic(
        _msg(msg_id="C9103", symbol="naming-convention-violation",
             line=1, column=27, end_line=1, end_column=34),
        [_ACCENTED],
    )
    assert d.range.start.character == 25
    assert d.range.end.character == 32


def test_pycodestyle_columns_are_character_offsets() -> None:
    # E9989 comes from pycodestyle, which counts characters, not bytes.
    d = to_diagnostic(
        _msg(msg_id="E9989", symbol="pep8-errors",
             line=1, column=18, end_line=None, end_column=None),
        [_ACCENTED_PEP8],
    )
    assert d.range.start.character == 18


def test_synthesized_syntax_error_columns_are_character_offsets() -> None:
    # E0001 comes from SyntaxError.offset, which counts characters.
    d = to_diagnostic(
        _msg(msg_id="E0001", symbol="syntax-error",
             line=1, column=25, end_line=None, end_column=None),
        [_ACCENTED],
    )
    assert d.range.start.character == 25
