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


def test_non_dict_non_string_literal_is_absent_with_warning() -> None:
    source = "import python_ta\npython_ta.check_all(config=5)\n"
    result = extract_config(ast.parse(source), Path("."))
    assert result.kind == "absent"
    assert result.value is None
    assert len(result.warnings) == 1
    assert "neither a dict nor a string" in result.warnings[0]


UNRELATED_FIRST = '''"""Doc."""
import suite

suite.check_all(config={'max-line-length': 200})

if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config={'max-line-length': 40})
'''

UNRELATED_ONLY = '''"""Doc."""
import suite

suite.check_all(config={'max-line-length': 200})
'''

ALIASED = '''"""Doc."""
import python_ta as pyta

pyta.check_all(config={'max-line-length': 60})
'''


def test_an_unrelated_check_all_does_not_supply_the_config(tmp_path: Path) -> None:
    # Any helper named check_all used to win purely by sorting first, and the
    # student would then be linted against settings the grader never applies.
    result = extract_config(ast.parse(UNRELATED_FIRST), tmp_path)

    assert result.kind == "dict"
    assert result.value == {"max-line-length": 40}


def test_a_file_with_only_an_unrelated_check_all_has_no_embedded_config(tmp_path: Path) -> None:
    assert extract_config(ast.parse(UNRELATED_ONLY), tmp_path).kind == "absent"


def test_an_aliased_python_ta_import_still_counts(tmp_path: Path) -> None:
    result = extract_config(ast.parse(ALIASED), tmp_path)

    assert result.kind == "dict"
    assert result.value == {"max-line-length": 60}


def test_load_default_config_is_extracted_from_the_call_that_supplies_the_config() -> None:
    # Without it the file is checked against PythonTA's defaults merged in, which
    # is not what the course file asked for or what the grader runs.
    source = (
        "import python_ta\n"
        "python_ta.check_all(config='course.txt', load_default_config=False)\n"
    )
    result = extract_config(ast.parse(source), Path("."))

    assert result.load_default_config is False


def test_load_default_config_is_unset_when_the_call_omits_it() -> None:
    source = "import python_ta\npython_ta.check_all(config={'a': 1})\n"

    assert extract_config(ast.parse(source), Path(".")).load_default_config is None


def test_load_default_config_is_read_even_without_a_config_keyword() -> None:
    source = "import python_ta\npython_ta.check_all(load_default_config=False)\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "absent"
    assert result.load_default_config is False


def test_nonliteral_load_default_config_is_ignored_with_a_warning() -> None:
    source = (
        "import python_ta\n"
        "STRICT = False\n"
        "python_ta.check_all(config={'a': 1}, load_default_config=STRICT)\n"
    )
    result = extract_config(ast.parse(source), Path("."))

    assert result.load_default_config is None
    assert any("load_default_config" in w for w in result.warnings)


def test_a_non_bool_load_default_config_is_ignored_with_a_warning() -> None:
    source = "import python_ta\npython_ta.check_all(load_default_config=0)\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.load_default_config is None
    assert any("load_default_config" in w for w in result.warnings)


def test_a_positional_config_dict_is_read() -> None:
    # check_all(module_name, config, output, load_default_config, ...). A config
    # passed by position was ignored without a word, so the student was checked
    # against stock defaults.
    source = "import python_ta\npython_ta.check_all('a1.py', {'extra-imports': ['random']})\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "dict"
    assert result.value == {"extra-imports": ["random"]}
    assert result.warnings == []


def test_a_positional_config_path_is_read(tmp_path: Path) -> None:
    source = "import python_ta\npython_ta.check_all('a1.py', 'course.txt')\n"
    result = extract_config(ast.parse(source), tmp_path)

    assert result.kind == "path"
    assert result.value == str(tmp_path / "course.txt")


def test_a_positional_load_default_config_is_read() -> None:
    source = (
        "import python_ta\n"
        "python_ta.check_all('a1.py', {'max-line-length': 100}, None, False)\n"
    )
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "dict"
    assert result.load_default_config is False


def test_a_keyword_config_still_wins_over_the_positional_slot() -> None:
    source = "import python_ta\npython_ta.check_all('a1.py', config={'a': 1})\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.value == {"a": 1}


def test_a_nonliteral_positional_config_warns_like_the_keyword_one() -> None:
    source = "import python_ta\nCFG = {'a': 1}\npython_ta.check_all('a1.py', CFG)\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "absent"
    assert any("not a literal" in w for w in result.warnings)


def test_a_starred_argument_list_is_not_guessed_at() -> None:
    # With *args in the call, nothing can be said about which slot holds what.
    source = "import python_ta\nARGS = ['a1.py']\npython_ta.check_all(*ARGS, {'a': 1})\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "absent"
    assert result.load_default_config is None
    assert any("*" in w for w in result.warnings), result.warnings


def test_a_keyword_config_is_read_even_beside_a_starred_argument_list() -> None:
    # *args hides the positions, not the keywords. The keyword is right there.
    source = "import python_ta\nARGS = ['a1.py']\npython_ta.check_all(*ARGS, config={'a': 1})\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "dict"
    assert result.value == {"a": 1}
    assert result.warnings == []


def test_a_starred_keyword_dict_is_not_guessed_at() -> None:
    # **CFG can carry config or load_default_config and there is no way to tell,
    # so this was silently checked against the defaults with nothing said.
    source = "import python_ta\nCFG = {'config': {'a': 1}}\npython_ta.check_all('a1.py', **CFG)\n"
    result = extract_config(ast.parse(source), Path("."))

    assert result.kind == "absent"
    assert result.load_default_config is None
    assert any("cannot be read" in w for w in result.warnings), result.warnings
