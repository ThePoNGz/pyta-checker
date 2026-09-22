import ast
from pathlib import Path

from pyta_lsp.config_extract import ExtractedConfig, extract_config


def _extract(fixtures: Path, name: str) -> ExtractedConfig:
    path = fixtures / name
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return extract_config(tree, path.parent)


def test_dict_config_is_extracted(fixtures: Path) -> None:
    result = _extract(fixtures, "course_style.py")
    assert result.kind == "dict"
    assert result.value == {
        "extra-imports": ["random", "datetime"],
        "allowed-io": ["roll"],
        "max-line-length": 100,
        "disable": ["C0200"],
    }
    assert result.errors_only is False
    assert result.warnings == []


def test_no_call_means_absent(fixtures: Path) -> None:
    result = _extract(fixtures, "no_config.py")
    assert result.kind == "absent"
    assert result.value is None
    assert result.errors_only is False


def test_string_config_resolves_relative_to_file(fixtures: Path) -> None:
    result = _extract(fixtures, "string_config.py")
    assert result.kind == "path"
    assert result.value == str(fixtures / "pyta_config.txt")


def test_check_errors_bare_name_sets_errors_only(fixtures: Path) -> None:
    result = _extract(fixtures, "check_errors_style.py")
    assert result.kind == "dict"
    assert result.value == {"max-line-length": 100}
    assert result.errors_only is True


def test_nonliteral_config_is_absent_with_warning(fixtures: Path) -> None:
    result = _extract(fixtures, "nonliteral_config.py")
    assert result.kind == "absent"
    assert result.value is None
    assert len(result.warnings) == 1
    assert "not a literal" in result.warnings[0]


def test_first_call_by_line_wins() -> None:
    source = (
        "import python_ta\n"
        "python_ta.check_all(config={'a': 1})\n"
        "python_ta.check_all(config={'b': 2})\n"
    )
    result = extract_config(ast.parse(source), Path("."))
    assert result.value == {"a": 1}


def test_call_without_config_keyword_is_absent_but_keeps_errors_only() -> None:
    source = "import python_ta\npython_ta.check_errors()\n"
    result = extract_config(ast.parse(source), Path("."))
    assert result.kind == "absent"
    assert result.errors_only is True


def test_absolute_string_config_is_kept() -> None:
    absolute = str(Path("/tmp/cfg.txt").resolve())
    source = f"import python_ta\npython_ta.check_all(config={absolute!r})\n"
    result = extract_config(ast.parse(source), Path("/elsewhere"))
    assert result.kind == "path"
    assert result.value == absolute
