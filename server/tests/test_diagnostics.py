from lsprotocol import types

from pyta_lsp.diagnostics import FAILURE_CODE, SOURCE, config_diagnostic, docs_url, failure_diagnostic, to_diagnostic


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


# Every line is BMP-only, so a character index and a UTF-16 unit index agree and
# each expected value can be read straight off the source text.
_COLUMN_SOURCE = (
    '"""Doc."""\n'
    'NAME = "café"   \n'
    'LABEL = "café"  # TODO: fix this\n'
    'PATTERN = "café \\d"\n'
    'UNI = "café"; DATA = b"x \\u0041"\n'
    'MIXED = "café"; COUNT: int = "many"\n'
)


def test_odd_column_conventions_land_where_the_source_says(tmp_path) -> None:
    # C0303 counts the stripped line, W0511 counts tokenize columns and
    # W1401/W1402 count into the string body. Those four are characters, so
    # decoding them as UTF-8 byte offsets drags the squiggle one column left for
    # every non-ASCII character earlier on the line. E9952 comes from mypy, whose
    # start column is a byte offset but a 1-based one, so it lands one right.
    from pyta_lsp.runner import run_check

    path = tmp_path / "columns.py"
    path.write_text(_COLUMN_SOURCE, encoding="utf-8")
    lines = _COLUMN_SOURCE.splitlines(keepends=True)
    expected = {
        "C0303": (2, len('NAME = "café"')),
        # pylint reports fixme one column past the "#" of the comment token.
        "W0511": (3, lines[2].index("#") + 1),
        "W1401": (4, lines[3].index("\\")),
        "W1402": (5, lines[4].index("\\")),
        "E9952": (6, lines[5].index('"many"')),
    }

    result = run_check(path)

    assert result["ok"] is True, result["error"]
    seen = {
        msg["msg_id"]: to_diagnostic(msg, lines).range.start
        for msg in result["messages"]
        if msg["msg_id"] in expected
    }
    assert set(seen) == set(expected), f"the fixture did not produce every code: {sorted(seen)}"
    for code, (line, character) in expected.items():
        assert seen[code] == types.Position(line - 1, character), f"{code} landed at {seen[code]}"


def test_a_mypy_end_column_is_not_shifted_with_its_start(tmp_path) -> None:
    # mypy's end column is 1-based inclusive, which is already the 0-based
    # exclusive offset every other code uses. Shifting it along with the start
    # would cut the last character off the squiggle.
    from pyta_lsp.runner import run_check

    path = tmp_path / "columns.py"
    path.write_text(_COLUMN_SOURCE, encoding="utf-8")
    lines = _COLUMN_SOURCE.splitlines(keepends=True)

    result = run_check(path)

    assert result["ok"] is True, result["error"]
    msg = next(m for m in result["messages"] if m["msg_id"] == "E9952")
    end = to_diagnostic(msg, lines).range.end
    assert end == types.Position(5, lines[5].index('"many"') + len('"many"'))


def test_a_config_file_message_is_an_information_diagnostic_on_line_one() -> None:
    # The student's own run prints this under the config file; here it has to
    # sit on the file being checked, marked as being about the config.
    diagnostic = config_diagnostic(
        {
            "filename": "C:/course/cfg.txt",
            "msg_id": "W0012",
            "symbol": "unknown-option-value",
            "msg": "Unknown option value for '--disable', expected a valid pylint message",
            "line": 2,
        }
    )
    assert diagnostic.severity == types.DiagnosticSeverity.Information
    assert diagnostic.code == "W0012"
    assert diagnostic.source == SOURCE
    assert diagnostic.range.start == types.Position(0, 0)
    assert "cfg.txt" in diagnostic.message
    assert "line 2" in diagnostic.message
    assert "Unknown option value" in diagnostic.message


def test_split_lines_only_breaks_where_python_and_the_editor_do() -> None:
    # str.splitlines also breaks on \x0c, \x0b, \x1c-\x1e, \x85, U+2028 and U+2029.
    # None of those is a line break to the tokenizer or to the editor, so from the
    # first one on every message lands on the wrong line.
    from pyta_lsp.diagnostics import split_lines

    assert split_lines("# note\x0cmore\nX = 1\n") == ["# note\x0cmore\n", "X = 1\n"]
    assert split_lines("a\r\nb\rc\nd") == ["a\r\n", "b\r", "c\n", "d"]
    assert split_lines("") == []
    assert split_lines("one line") == ["one line"]
    assert split_lines("a\x85b c\n") == ["a\x85b c\n"]
