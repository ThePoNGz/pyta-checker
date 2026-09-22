# PythonTA Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A VS Code extension that shows exactly what PythonTA will flag as squiggles, with PythonTA bundled inside the extension and the course's embedded `check_all(config=...)` honored, backed by a standalone language server.

**Architecture:** Three layers in one repo. A one-shot Python runner (`pyta_lsp.runner`) parses a file, extracts the embedded config, runs `python_ta` with the JSON reporter, and prints JSON. A pygls 2 language server (`pyta_lsp.server`) runs the runner in a subprocess on open/save/command and publishes LSP diagnostics. A TypeScript extension launches the server with the student's interpreter and `bundled/libs` on `PYTHONPATH`, adds commands, a status bar, and an opt-in mode that hides Pylance/basedpyright diagnostics.

**Tech Stack:** Python 3.10+ (python-ta 2.13.1, pygls 2.1.x, lsprotocol 2025.0.0, pytest 8, pytest-lsp 1.0.x), TypeScript 5.9 (vscode-languageclient 10.1.x, @vscode/python-extension 1.0.6, esbuild, vitest, @vscode/test-cli, @vscode/vsce 4), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-22-pyta-checker-design.md`

## Global Constraints

- Repo root: `C:\Users\ThePong\Desktop\Dev\pyta-checker`. Git remote `origin` = `https://github.com/ThePoNGz/pyta-checker.git`, branch `main`. All commands below run from the repo root unless stated.
- Python floor: `>=3.10` everywhere (server package, bundle, CI matrix). Dev interpreter on this machine is Python 3.14 at `python`; the project venv is `.venv` (Windows: `.venv\Scripts\python.exe`, POSIX: `.venv/bin/python`). Write `PY=.venv/Scripts/python` on Windows Git Bash or `PY=.venv/bin/python` elsewhere and use `$PY` in commands.
- Pins: `python-ta==2.13.1`, `pygls>=2.1,<3` (pygls pins `lsprotocol==2025.0.0`), `vscode-languageclient ^10.1.1`, `@vscode/python-extension ^1.0.6`, `engines.vscode ^1.101.0`, Node 22+ in CI (local Node 26 is fine).
- pygls 2 API only: `from pygls.lsp.server import LanguageServer`; publish with `ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(...))`; log with `ls.window_log_message(types.LogMessageParams(...))`; custom notifications with `ls.protocol.notify(method, params)`. Never use v1 names (`publish_diagnostics`, `show_message`, `server.lsp`).
- vscode-languageclient 10: `tsconfig` must use `"module": "Node16"`, `"moduleResolution": "Node16"`; `outputChannel` must be a `LogOutputChannel` (`createOutputChannel(name, { log: true })`); import from `'vscode-languageclient/node'`.
- Never execute student code. The runner only parses with `ast` and hands the path to `python_ta`.
- Subprocess environments always include `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`.
- Diagnostic `source` is exactly `"PythonTA"`. Failure diagnostic `code` is `"pyta-error"`. Server command id is `"pyta.check"`. Status notification method is `"pyta/status"`. Settings section is `pythonta`. Extension command ids are `pythonta.check`, `pythonta.restart`, `pythonta.toggleOnlyPyta`, `pythonta.showOutput`.
- Position rules: pyta `line` is 1-based, `column`/`end_column` are 0-based Python string indices with exclusive end; LSP is 0-based with UTF-16 code units. `category == "error"` or `"fatal"` maps to Error, everything else to Warning.
- Docs URL rule: if the uppercase `msg_id` is in the generated set `PYTA_DOCUMENTED_CODES`, link `https://www.cs.toronto.edu/~david/pyta/checkers/index.html#<msg_id lowercased>`; otherwise `https://pylint.readthedocs.io/en/stable/user_guide/messages/<dir>/<symbol lowercased>.html` with dir from the first letter (`F` fatal, `E` error, `W` warning, `C` convention, `R` refactor, `I` information); otherwise the pyta page with no fragment.
- No third-party source is committed. `bundled/libs/` is gitignored and built by `scripts/bundle.py`. No code is copied from `pyta-uoft/*` extensions or Microsoft's template.
- Licensing text: `LICENSE` is MIT, `Copyright (c) 2026 ThePoNGz`.
- Commits: conventional prefixes (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `ci:`), no `Co-Authored-By` lines (user's global rule). Line endings LF (`.gitattributes`).
- Comments in code: minimal, only about logic.
- The old empty folder `C:\Users\ThePong\Desktop\Dev\vscode-pyta` is not the project. Ignore it.

## File map

| Path | Responsibility |
| --- | --- |
| `server/pyproject.toml` | Python package `pyta-lsp`, module `pyta_lsp`, console script, pytest config |
| `server/requirements.in`, `server/requirements.lock` | top-level pins and the universal lock used to build `bundled/libs` |
| `server/pyta_lsp/__init__.py` | `__version__` |
| `server/pyta_lsp/config_extract.py` | AST extraction of `check_all(config=...)` |
| `server/pyta_lsp/pyta_codes.py` | generated set of message codes documented on the pyta site |
| `server/pyta_lsp/diagnostics.py` | pyta JSON message to `lsprotocol` Diagnostic, docs URL, failure diagnostic |
| `server/pyta_lsp/runner.py` | one-shot checker CLI: `python -m pyta_lsp.runner <file>` |
| `server/pyta_lsp/scheduler.py` | per-document subprocess scheduling with supersede/kill/timeout |
| `server/pyta_lsp/server.py` | pygls server, handlers, settings |
| `server/pyta_lsp/__main__.py` | `python -m pyta_lsp` entry |
| `server/tests/*.py` | pytest suites |
| `test/fixtures/*.py` | sample Python files shared by Python tests and the VS Code integration test |
| `scripts/gen_pyta_codes.py` | regenerates `pyta_codes.py` from the pyta docs page |
| `scripts/bundle.py` | `lock` and `build` subcommands for `bundled/libs` and `THIRD_PARTY_NOTICES.md` |
| `package.json`, `tsconfig.json`, `esbuild.mjs`, `eslint.config.mjs`, `vitest.config.mts`, `.vscode-test.mjs`, `.vscodeignore` | extension manifest and tooling |
| `src/pythonVersion.ts` | pure: parse `major.minor`, support check |
| `src/python.ts` | interpreter discovery (setting, Python extension API, PATH probe) |
| `src/settings.ts` | typed read of the `pythonta` section |
| `src/client.ts` | LanguageClient creation, server options/env, check request, status notification |
| `src/statusBar.ts` | status bar item |
| `src/onlyPytaLogic.ts` | pure: plan settings writes for enable/disable |
| `src/onlyPyta.ts` | prompt, apply writes, restart other language servers |
| `src/extension.ts` | activate/deactivate wiring, commands, restarts |
| `test/unit/*.test.ts` | vitest unit tests for pure modules |
| `test/integration/*.test.ts`, `test/integration/helpers.ts` | @vscode/test-cli suite |
| `.github/workflows/ci.yml`, `.github/workflows/release.yml` | CI and release |
| `README.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` | docs and licensing |

---

### Task 1: Repository scaffold and Python package skeleton

**Files:**
- Create: `.gitignore`, `.gitattributes`, `.editorconfig`, `LICENSE`, `README.md` (stub), `CHANGELOG.md`
- Create: `server/pyproject.toml`, `server/README.md`, `server/pyta_lsp/__init__.py`, `server/tests/__init__.py`, `server/tests/test_version.py`

**Interfaces:**
- Produces: `pyta_lsp.__version__: str` (`"0.1.0"`), a working `.venv` with `pyta-lsp[dev]` installed editable.

- [ ] **Step 1: Write repo-level dotfiles and license**

`.gitignore`:
```
# Python
.venv/
__pycache__/
*.pyc
*.egg-info/
build/
dist/
server/dist/
.pytest_cache/
# Node
node_modules/
out/
*.vsix
.vscode-test/
# Bundle output (built by scripts/bundle.py)
bundled/libs/
# Editors / OS
.DS_Store
Thumbs.db
```

`.gitattributes`:
```
* text=auto eol=lf
*.png binary
*.ico binary
```

`.editorconfig`:
```
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 4
trim_trailing_whitespace = true

[*.{ts,mts,js,mjs,json,yml,yaml,md}]
indent_size = 2

[*.md]
trim_trailing_whitespace = false
```

`LICENSE`:
```
MIT License

Copyright (c) 2026 ThePoNGz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`README.md` (stub, replaced in Task 12):
```markdown
# PythonTA Checker

VS Code extension that shows exactly what PythonTA will flag, with PythonTA bundled in. Work in progress; see `docs/superpowers/specs/`.
```

`CHANGELOG.md`:
```markdown
# Changelog

## Unreleased

- Initial development.
```

- [ ] **Step 2: Write the Python package skeleton**

`server/pyproject.toml`:
```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "pyta-lsp"
version = "0.1.0"
description = "Language server for PythonTA that honors the check_all(config=...) block embedded in course files"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
dependencies = [
    "pygls>=2.1,<3",
    "python-ta==2.13.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=1.0",
    "pytest-lsp>=1.0.1",
]

[project.scripts]
pyta-lsp = "pyta_lsp.__main__:main"

[tool.hatch.build.targets.wheel]
packages = ["pyta_lsp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`server/README.md`:
```markdown
# pyta-lsp

Language server for PythonTA. Run with `python -m pyta_lsp` (stdio). Part of the PythonTA Checker VS Code extension; usable from any LSP-capable editor.
```

`server/pyta_lsp/__init__.py`:
```python
__version__ = "0.1.0"
```

`server/tests/__init__.py`: empty file.

- [ ] **Step 3: Write the smoke test**

`server/tests/test_version.py`:
```python
import pyta_lsp


def test_version_is_semver() -> None:
    major, minor, patch = pyta_lsp.__version__.split(".")
    assert all(part.isdigit() for part in (major, minor, patch))
```

- [ ] **Step 4: Create the venv, install, run the test**

```bash
python -m venv .venv
PY=.venv/Scripts/python   # POSIX: PY=.venv/bin/python
$PY -m pip install --upgrade pip
$PY -m pip install -e "server[dev]"
$PY -m pytest server/tests -q
```
Expected: `1 passed`. (`python-ta==2.13.1` and `pygls` install from PyPI; this takes a minute.)

- [ ] **Step 5: Commit**

```bash
git add .gitignore .gitattributes .editorconfig LICENSE README.md CHANGELOG.md server
git commit -m "chore: scaffold repo and pyta-lsp package skeleton"
```

---

### Task 2: Fixtures and embedded-config extraction

**Files:**
- Create: `test/fixtures/course_style.py`, `test/fixtures/no_config.py`, `test/fixtures/string_config.py`, `test/fixtures/pyta_config.txt`, `test/fixtures/check_errors_style.py`, `test/fixtures/nonliteral_config.py`, `test/fixtures/syntax_error.py`, `test/fixtures/clean.py`
- Create: `server/pyta_lsp/config_extract.py`, `server/tests/conftest.py`, `server/tests/test_config_extract.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class ExtractedConfig:
      kind: Literal["dict", "path", "absent"]
      value: dict[str, Any] | str | None
      errors_only: bool
      warnings: list[str]
  def extract_config(tree: ast.AST, base_dir: Path) -> ExtractedConfig
  ```
- Produces fixture `FIXTURES: Path` in conftest pointing at `test/fixtures`.

- [ ] **Step 1: Write the fixture files**

`test/fixtures/course_style.py` (this exact content; line numbers matter for tests):
```python
"""Sample CSC148-style file with an embedded PythonTA config."""
import random
from datetime import datetime


def roll(n: int) -> int:
    """Roll n dice.

    >>> roll(0)
    0
    """
    total=0
    for i in range(n):
        total += random.randint(1, 6)
    print(total)
    return total


if __name__ == '__main__':
    import doctest

    doctest.testmod(verbose=True)

    import python_ta

    python_ta.check_all(config={
        'extra-imports': ['random', 'datetime'],
        'allowed-io': ['roll'],
        'max-line-length': 100,
        'disable': ['C0200']
    })
```

`test/fixtures/no_config.py`:
```python
"""Same code, no embedded config."""
import random
from datetime import datetime


def roll(n: int) -> int:
    """Roll n dice.

    >>> roll(0)
    0
    """
    total=0
    for i in range(n):
        total += random.randint(1, 6)
    print(total)
    return total
```

`test/fixtures/string_config.py`:
```python
"""Config given as a path string."""
import random


def pick() -> int:
    """Return a random number."""
    return random.randint(1, 6)


if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config='pyta_config.txt')
```

`test/fixtures/pyta_config.txt`:
```
[FORBIDDEN IMPORT]
extra-imports = random

[FORMAT]
max-line-length = 100
```

`test/fixtures/check_errors_style.py`:
```python
"""Uses check_errors with a bare name import."""
from python_ta import check_errors


def add(a: int, b: int) -> int:
    """Add."""
    return a + b


if __name__ == '__main__':
    check_errors(config={'max-line-length': 100})
```

`test/fixtures/nonliteral_config.py`:
```python
"""Config is a variable, not a literal."""
CONFIG = {'max-line-length': 100}


def f() -> None:
    """Do nothing."""


if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config=CONFIG)
```

`test/fixtures/syntax_error.py`:
```python
"""Broken on purpose."""


def f(:
    return 1
```

`test/fixtures/clean.py`:
```python
"""A file PythonTA should not complain about."""


def add(a: int, b: int) -> int:
    """Return the sum of a and b.

    >>> add(1, 2)
    3
    """
    return a + b


if __name__ == '__main__':
    import python_ta

    python_ta.check_all(config={'max-line-length': 100})
```

- [ ] **Step 2: Write conftest and the failing extraction tests**

`server/tests/conftest.py`:
```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures"


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
```

`server/tests/test_config_extract.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
$PY -m pytest server/tests/test_config_extract.py -q
```
Expected: ImportError / ModuleNotFoundError for `pyta_lsp.config_extract`.

- [ ] **Step 4: Implement `config_extract.py`**

`server/pyta_lsp/config_extract.py`:
```python
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


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _check_calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    calls = [
        (name, node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (name := _callee_name(node)) in CHECK_FUNCTIONS
    ]
    calls.sort(key=lambda item: (item[1].lineno, item[1].col_offset))
    return calls


def extract_config(tree: ast.AST, base_dir: Path) -> ExtractedConfig:
    calls = _check_calls(tree)
    if not calls:
        return ExtractedConfig("absent", None, False)

    errors_only = calls[0][0] == "check_errors"
    for name, call in calls:
        config_kw = next((kw for kw in call.keywords if kw.arg == "config"), None)
        if config_kw is None:
            continue
        errors_only = name == "check_errors"
        try:
            value = ast.literal_eval(config_kw.value)
        except (ValueError, SyntaxError, TypeError):
            return ExtractedConfig(
                "absent",
                None,
                errors_only,
                [f"line {call.lineno}: config argument to {name}() is not a literal; using defaults"],
            )
        if isinstance(value, dict):
            return ExtractedConfig("dict", value, errors_only)
        if isinstance(value, str):
            path = Path(value)
            if not path.is_absolute():
                path = base_dir / path
            return ExtractedConfig("path", str(path), errors_only)
        return ExtractedConfig(
            "absent",
            None,
            errors_only,
            [f"line {call.lineno}: config argument to {name}() is neither a dict nor a string; using defaults"],
        )
    return ExtractedConfig("absent", None, errors_only)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
$PY -m pytest server/tests/test_config_extract.py -q
```
Expected: `8 passed`.

- [ ] **Step 6: Commit**

```bash
git add test/fixtures server/pyta_lsp/config_extract.py server/tests/conftest.py server/tests/test_config_extract.py
git commit -m "feat(server): extract embedded check_all config from files"
```

---

### Task 3: Documented-code set and diagnostic mapping

**Files:**
- Create: `scripts/gen_pyta_codes.py`, `server/pyta_lsp/pyta_codes.py` (generated), `server/pyta_lsp/diagnostics.py`
- Test: `server/tests/test_pyta_codes.py`, `server/tests/test_diagnostics.py`

**Interfaces:**
- Produces:
  ```python
  PYTA_DOCUMENTED_CODES: frozenset[str]           # uppercase codes, e.g. "E9989"
  SOURCE = "PythonTA"; FAILURE_CODE = "pyta-error"
  def docs_url(msg_id: str, symbol: str) -> str
  def to_diagnostic(msg: dict, lines: Sequence[str] | None) -> lsprotocol.types.Diagnostic
  def failure_diagnostic(reason: str) -> lsprotocol.types.Diagnostic
  ```

- [ ] **Step 1: Write the generator script and the failing codes test**

`scripts/gen_pyta_codes.py`:
```python
"""Regenerate server/pyta_lsp/pyta_codes.py from the PythonTA checkers page.

The page marks every documented message with an anchor id equal to the
lowercased message id (e.g. id="e9989").
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

PAGE = "https://www.cs.toronto.edu/~david/pyta/checkers/index.html"
OUT = Path(__file__).resolve().parents[1] / "server" / "pyta_lsp" / "pyta_codes.py"
ANCHOR = re.compile(r'id="([a-z][0-9]{4})"')


def main() -> int:
    with urllib.request.urlopen(PAGE, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    codes = sorted({m.upper() for m in ANCHOR.findall(html)})
    if len(codes) < 100:
        print(f"only found {len(codes)} codes; page layout may have changed", file=sys.stderr)
        return 1
    body = ",\n".join(f'    "{code}"' for code in codes)
    OUT.write_text(
        '"""Message codes documented on the PythonTA checkers page. Generated by scripts/gen_pyta_codes.py."""\n'
        "PYTA_DOCUMENTED_CODES: frozenset[str] = frozenset([\n"
        f"{body},\n"
        "])\n",
        encoding="utf-8",
    )
    print(f"wrote {len(codes)} codes to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`server/tests/test_pyta_codes.py`:
```python
from pyta_lsp.pyta_codes import PYTA_DOCUMENTED_CODES


def test_known_documented_codes_present() -> None:
    for code in ("E9989", "E9998", "E9999", "C0201", "R0912"):
        assert code in PYTA_DOCUMENTED_CODES


def test_known_undocumented_codes_absent() -> None:
    for code in ("C0114", "C0200", "R1705", "R9901"):
        assert code not in PYTA_DOCUMENTED_CODES


def test_codes_are_uppercase_five_chars() -> None:
    assert all(len(c) == 5 and c[0].isupper() and c[1:].isdigit() for c in PYTA_DOCUMENTED_CODES)
```

- [ ] **Step 2: Generate the module and run the codes test**

```bash
$PY scripts/gen_pyta_codes.py
$PY -m pytest server/tests/test_pyta_codes.py -q
```
Expected: `wrote 18x codes ...` then `3 passed`. If `R9901` turns out present, remove it from the undocumented assertion (the page had no short anchor for it on 2026-09-22).

- [ ] **Step 3: Write the failing diagnostics tests**

`server/tests/test_diagnostics.py`:
```python
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
    assert d.code_description.href.endswith("/warning/unused-variable.html")


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


def test_columns_are_utf16_units() -> None:
    lines = ["s = '😀😀'; y=1\n"]
    # Python index of "y" is 10; the two emoji occupy 4 UTF-16 units instead of 2.
    d = to_diagnostic(_msg(line=1, column=10, end_line=1, end_column=11), lines)
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
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
$PY -m pytest server/tests/test_diagnostics.py -q
```
Expected: ModuleNotFoundError for `pyta_lsp.diagnostics`.

- [ ] **Step 5: Implement `diagnostics.py`**

`server/pyta_lsp/diagnostics.py`:
```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
$PY -m pytest server/tests/test_diagnostics.py server/tests/test_pyta_codes.py -q
```
Expected: `11 passed`.

- [ ] **Step 7: Commit**

```bash
git add scripts/gen_pyta_codes.py server/pyta_lsp/pyta_codes.py server/pyta_lsp/diagnostics.py server/tests/test_pyta_codes.py server/tests/test_diagnostics.py
git commit -m "feat(server): map PythonTA messages to LSP diagnostics with docs links"
```

---

### Task 4: The runner

**Files:**
- Create: `server/pyta_lsp/runner.py`
- Test: `server/tests/test_runner.py`

**Interfaces:**
- Consumes: `extract_config(tree, base_dir) -> ExtractedConfig` (Task 2).
- Produces:
  ```python
  ENV_LIBS = "PYTA_LSP_LIBS"; ENV_STRATEGY = "PYTA_LSP_IMPORT_STRATEGY"
  def apply_import_strategy(env: Mapping[str, str] = os.environ, path: list[str] = sys.path) -> None
  def run_check(path: Path, *, config_path: str | None = None, errors_only: bool = False,
                use_embedded: bool = True, workspace_root: str | None = None) -> dict[str, Any]
  def main(argv: list[str] | None = None) -> int      # python -m pyta_lsp.runner <file> [--config P] [--errors-only] [--no-embedded-config] [--workspace-root D]
  ```
  Result dict keys: `ok`, `config_source` (`"embedded" | "file" | "default"`), `messages` (pyta JSON messages), `log`, `warnings`, `error`, `traceback`, `pyta_version`, `pyta_location`.

- [ ] **Step 1: Write the failing runner tests**

`server/tests/test_runner.py`:
```python
import json
import os
import subprocess
import sys
from pathlib import Path

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
$PY -m pytest server/tests/test_runner.py -q
```
Expected: ModuleNotFoundError for `pyta_lsp.runner`.

- [ ] **Step 3: Implement `runner.py`**

`server/pyta_lsp/runner.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
$PY -m pytest server/tests/test_runner.py -q
```
Expected: `12 passed` (each pyta run takes a few seconds; the file takes about a minute). If `test_clean_file_has_no_messages` fails, read the reported codes and adjust `test/fixtures/clean.py` until pyta is satisfied (for example rename short parameters). Do not loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add server/pyta_lsp/runner.py server/tests/test_runner.py test/fixtures
git commit -m "feat(server): one-shot runner that honors embedded configs and reports JSON"
```

---

### Task 5: Scheduler and language server

**Files:**
- Create: `server/pyta_lsp/scheduler.py`, `server/pyta_lsp/server.py`, `server/pyta_lsp/__main__.py`
- Test: `server/tests/test_scheduler.py`, `server/tests/test_server.py`

**Interfaces:**
- Consumes: `to_diagnostic`, `failure_diagnostic` (Task 3); the runner CLI (Task 4).
- Produces:
  ```python
  class CheckScheduler:
      def __init__(self, spawn: Callable[[list[str], str], subprocess.Popen] = default_spawn, timeout: float = 60.0)
      def run(self, key: str, argv: list[str], cwd: str) -> dict[str, Any] | None   # None = superseded
      def cancel(self, key: str) -> None
  class Settings: run_on_save, run_on_open, config_path; Settings.from_dict(data)
  class PytaLanguageServer(LanguageServer): settings, scheduler, workspace_root; check(uri); clear(uri); notify_status(uri, state, count)
  server: PytaLanguageServer
  STATUS_NOTIFICATION = "pyta/status"; CHECK_COMMAND = "pyta.check"
  ```
  Status notification params: `{"uri": str, "state": "checking" | "done", "count": int | None}`.

- [ ] **Step 1: Write the failing scheduler tests**

`server/tests/test_scheduler.py`:
```python
import sys
import threading
import time
from pathlib import Path

from pyta_lsp.scheduler import CheckScheduler


def _echo_argv(tag: str, delay: float = 0.0) -> list[str]:
    code = (
        "import json, sys, time; "
        f"time.sleep({delay}); "
        f"sys.stdout.write(json.dumps({{'ok': True, 'messages': [], 'tag': {tag!r}}}))"
    )
    return [sys.executable, "-c", code]


def test_run_returns_parsed_json(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    result = scheduler.run("doc", _echo_argv("one"), str(tmp_path))
    assert result == {"ok": True, "messages": [], "tag": "one"}


def test_newer_request_supersedes_older(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def slow() -> None:
        results["first"] = scheduler.run("doc", _echo_argv("slow", delay=5), str(tmp_path))

    thread = threading.Thread(target=slow)
    thread.start()
    time.sleep(0.5)
    results["second"] = scheduler.run("doc", _echo_argv("fast"), str(tmp_path))
    thread.join(timeout=30)
    assert results["first"] is None
    assert results["second"]["tag"] == "fast"  # type: ignore[index]


def test_timeout_is_reported(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=0.5)
    result = scheduler.run("doc", [sys.executable, "-c", "import time; time.sleep(30)"], str(tmp_path))
    assert result is not None
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_nonzero_exit_uses_last_stderr_line(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys; sys.stderr.write('boom\\nlast line\\n'); sys.exit(2)"]
    result = CheckScheduler(timeout=30).run("doc", argv, str(tmp_path))
    assert result["ok"] is False
    assert result["error"] == "last line"


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "print('not json')"]
    result = CheckScheduler(timeout=30).run("doc", argv, str(tmp_path))
    assert result["ok"] is False
    assert "not JSON" in result["error"]


def test_different_keys_run_independently(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def run(key: str) -> None:
        results[key] = scheduler.run(key, _echo_argv(key, delay=1), str(tmp_path))

    threads = [threading.Thread(target=run, args=(k,)) for k in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert results["a"]["tag"] == "a"  # type: ignore[index]
    assert results["b"]["tag"] == "b"  # type: ignore[index]


def test_cancel_kills_in_flight(tmp_path: Path) -> None:
    scheduler = CheckScheduler(timeout=30)
    results: dict[str, object] = {}

    def slow() -> None:
        results["r"] = scheduler.run("doc", _echo_argv("slow", delay=10), str(tmp_path))

    thread = threading.Thread(target=slow)
    thread.start()
    time.sleep(0.5)
    scheduler.cancel("doc")
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert results["r"] is None
```

- [ ] **Step 2: Run scheduler tests to verify they fail**

```bash
$PY -m pytest server/tests/test_scheduler.py -q
```
Expected: ModuleNotFoundError for `pyta_lsp.scheduler`.

- [ ] **Step 3: Implement `scheduler.py`**

`server/pyta_lsp/scheduler.py`:
```python
"""Run the runner subprocess per document. A newer request kills and supersedes an older one."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Any, Callable

Spawn = Callable[[list[str], str], subprocess.Popen]


def runner_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def default_spawn(argv: list[str], cwd: str) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=runner_env(),
        **kwargs,
    )


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass


def _failure(error: str, log: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "messages": [], "log": log, "warnings": [], "traceback": None}


def _interpret(out: bytes, err: bytes, returncode: int | None, timed_out: bool, timeout: float) -> dict[str, Any]:
    stderr = err.decode("utf-8", errors="replace").strip()
    if timed_out:
        return _failure(f"timed out after {int(timeout)} seconds", stderr)
    stdout = out.decode("utf-8", errors="replace").strip()
    if returncode != 0 or not stdout:
        last = stderr.splitlines()[-1] if stderr else f"runner exited with code {returncode}"
        return _failure(last, stderr)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return _failure("runner output was not JSON", stdout[-2000:])
    if not isinstance(data, dict):
        return _failure("runner output had an unexpected shape", stdout[-2000:])
    return data


class CheckScheduler:
    def __init__(self, spawn: Spawn = default_spawn, timeout: float = 60.0) -> None:
        self._spawn = spawn
        self._timeout = timeout
        self._lock = threading.Lock()
        self._generation: dict[str, int] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    def run(self, key: str, argv: list[str], cwd: str) -> dict[str, Any] | None:
        with self._lock:
            generation = self._generation.get(key, 0) + 1
            self._generation[key] = generation
            previous = self._procs.pop(key, None)
        if previous is not None:
            _kill(previous)

        proc = self._spawn(argv, cwd)
        with self._lock:
            superseded = self._generation[key] != generation
            if not superseded:
                self._procs[key] = proc
        if superseded:
            _kill(proc)
            return None

        timed_out = False
        try:
            out, err = proc.communicate(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            out, err = proc.communicate()
            timed_out = True

        with self._lock:
            if self._procs.get(key) is proc:
                del self._procs[key]
            if self._generation[key] != generation:
                return None
        return _interpret(out, err, proc.returncode, timed_out, self._timeout)

    def cancel(self, key: str) -> None:
        with self._lock:
            self._generation[key] = self._generation.get(key, 0) + 1
            proc = self._procs.pop(key, None)
        if proc is not None:
            _kill(proc)
```

- [ ] **Step 4: Run scheduler tests to verify they pass**

```bash
$PY -m pytest server/tests/test_scheduler.py -q
```
Expected: `7 passed`.

- [ ] **Step 5: Write the failing server tests**

`server/tests/test_server.py`:
```python
import sys
from collections.abc import AsyncGenerator

import pytest_lsp
from lsprotocol import types
from pytest_lsp import ClientServerConfig, LanguageClient

from .conftest import FIXTURES


@pytest_lsp.fixture(config=ClientServerConfig(server_command=[sys.executable, "-m", "pyta_lsp"]))
async def client(lsp_client: LanguageClient) -> AsyncGenerator[None, None]:
    await lsp_client.initialize_session(
        types.InitializeParams(
            capabilities=types.ClientCapabilities(),
            root_uri=FIXTURES.as_uri(),
            initialization_options={"runOnOpen": True, "runOnSave": True, "configPath": ""},
        )
    )
    yield
    await lsp_client.shutdown_session()


def _open(client: LanguageClient, name: str) -> str:
    path = FIXTURES / name
    uri = path.as_uri()
    client.text_document_did_open(
        types.DidOpenTextDocumentParams(
            text_document=types.TextDocumentItem(
                uri=uri, language_id="python", version=1, text=path.read_text(encoding="utf-8")
            )
        )
    )
    return uri


async def test_open_publishes_diagnostics_honoring_embedded_config(client: LanguageClient) -> None:
    uri = _open(client, "course_style.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    diagnostics = client.diagnostics[uri]
    codes = {d.code for d in diagnostics}
    assert "E9989" in codes
    assert "E9999" not in codes
    assert all(d.source == "PythonTA" for d in diagnostics)
    pep8 = next(d for d in diagnostics if d.code == "E9989")
    assert pep8.range.start == types.Position(line=11, character=9)
    assert pep8.range.end == types.Position(line=11, character=len("    total=0"))
    assert pep8.code_description is not None
    assert pep8.code_description.href.endswith("#e9989")


async def test_close_clears_diagnostics(client: LanguageClient) -> None:
    uri = _open(client, "no_config.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert client.diagnostics[uri]
    client.text_document_did_close(
        types.DidCloseTextDocumentParams(text_document=types.TextDocumentIdentifier(uri=uri))
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    assert client.diagnostics[uri] == []


async def test_syntax_error_is_reported(client: LanguageClient) -> None:
    uri = _open(client, "syntax_error.py")
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    codes = [d.code for d in client.diagnostics[uri]]
    assert codes == ["E0001"]
    assert client.diagnostics[uri][0].range.start.line == 3


async def test_execute_command_checks_a_document(client: LanguageClient) -> None:
    uri = (FIXTURES / "no_config.py").as_uri()
    await client.workspace_execute_command_async(
        types.ExecuteCommandParams(command="pyta.check", arguments=[uri])
    )
    await client.wait_for_notification(types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
    codes = {d.code for d in client.diagnostics[uri]}
    assert "E9999" in codes


async def test_server_advertises_check_command(client: LanguageClient) -> None:
    provider = client.capabilities.execute_command_provider  # type: ignore[union-attr]
    assert provider is not None
    assert "pyta.check" in provider.commands
```

If `client.capabilities` is not the attribute pytest-lsp exposes for the server's `InitializeResult`, read `pytest_lsp/client.py` in the venv (`$PY -c "import pytest_lsp.client as c; print(c.__file__)"`) and use the attribute that holds the server capabilities; do not delete the test.

- [ ] **Step 6: Run server tests to verify they fail**

```bash
$PY -m pytest server/tests/test_server.py -q
```
Expected: failures because `python -m pyta_lsp` has no `__main__` yet (the server command exits immediately).

- [ ] **Step 7: Implement `server.py` and `__main__.py`**

`server/pyta_lsp/server.py`:
```python
"""pygls language server that runs PythonTA through the runner subprocess."""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

from lsprotocol import types
from pygls import uris
from pygls.lsp.server import LanguageServer

from . import __version__
from .diagnostics import failure_diagnostic, to_diagnostic
from .scheduler import CheckScheduler

log = logging.getLogger("pyta_lsp")
STATUS_NOTIFICATION = "pyta/status"
CHECK_COMMAND = "pyta.check"
CONFIG_SECTION = "pythonta"


@dataclass
class Settings:
    run_on_save: bool = True
    run_on_open: bool = True
    config_path: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        section = data.get(CONFIG_SECTION) if isinstance(data.get(CONFIG_SECTION), dict) else data
        return cls(
            run_on_save=bool(section.get("runOnSave", True)),
            run_on_open=bool(section.get("runOnOpen", True)),
            config_path=str(section.get("configPath") or ""),
        )


class PytaLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__(name="pyta-lsp", version=__version__, max_workers=4)
        self.settings = Settings()
        self.scheduler = CheckScheduler()
        self.workspace_root: str | None = None

    def notify_status(self, uri: str, state: str, count: int | None = None) -> None:
        self.protocol.notify(STATUS_NOTIFICATION, {"uri": uri, "state": state, "count": count})

    def log_to_client(self, message: str, level: types.MessageType = types.MessageType.Log) -> None:
        self.window_log_message(types.LogMessageParams(type=level, message=message))

    def check(self, uri: str) -> None:
        path = uris.to_fs_path(uri)
        if not path:
            return
        doc = self.workspace.get_text_document(uri)
        if doc.language_id not in (None, "python"):
            return
        self.notify_status(uri, "checking")
        argv = [sys.executable, "-m", "pyta_lsp.runner", path]
        if self.settings.config_path:
            argv += ["--config", self.settings.config_path]
            if self.workspace_root:
                argv += ["--workspace-root", self.workspace_root]
        result = self.scheduler.run(uri, argv, os.path.dirname(path))
        if result is None:
            return
        if result.get("ok"):
            diagnostics = [to_diagnostic(m, doc.lines) for m in result.get("messages", [])]
            for warning in result.get("warnings", []):
                self.log_to_client(f"{path}: {warning}", types.MessageType.Warning)
        else:
            reason = str(result.get("error") or "unknown error")
            diagnostics = [failure_diagnostic(reason)]
            detail = "\n".join(s for s in (result.get("traceback"), result.get("log")) if s)
            self.log_to_client(f"PythonTA failed on {path}: {reason}\n{detail}", types.MessageType.Error)
        self.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )
        self.notify_status(uri, "done", len(diagnostics))

    def clear(self, uri: str) -> None:
        self.scheduler.cancel(uri)
        self.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


server = PytaLanguageServer()


@server.feature(types.INITIALIZE)
def on_initialize(ls: PytaLanguageServer, params: types.InitializeParams) -> None:
    ls.settings = Settings.from_dict(params.initialization_options)
    folders = params.workspace_folders or []
    if folders:
        ls.workspace_root = uris.to_fs_path(folders[0].uri)
    elif params.root_uri:
        ls.workspace_root = uris.to_fs_path(params.root_uri)


@server.thread()
@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: PytaLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    if ls.settings.run_on_open:
        ls.check(params.text_document.uri)


@server.thread()
@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: PytaLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    if ls.settings.run_on_save:
        ls.check(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: PytaLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    ls.clear(params.text_document.uri)


@server.thread()
@server.command(CHECK_COMMAND)
def command_check(ls: PytaLanguageServer, uri: str) -> None:
    ls.check(uri)


@server.thread()
@server.feature(types.WORKSPACE_DID_CHANGE_CONFIGURATION)
def did_change_configuration(ls: PytaLanguageServer, params: types.DidChangeConfigurationParams) -> None:
    settings: Any = None
    try:
        items = ls.workspace_configuration(
            types.ConfigurationParams(items=[types.ConfigurationItem(section=CONFIG_SECTION)])
        ).result(5)
        if items and isinstance(items[0], dict):
            settings = items[0]
    except Exception as exc:  # clients without workspace/configuration support
        log.debug("workspace/configuration unavailable: %s", exc)
    if settings is None and isinstance(params.settings, dict):
        settings = params.settings
    if settings is not None:
        ls.settings = Settings.from_dict(settings)
```

`server/pyta_lsp/__main__.py`:
```python
"""Entry point for `python -m pyta_lsp` and the `pyta-lsp` console script."""
from __future__ import annotations

import logging
import sys


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[pyta-lsp] %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    from .server import server

    server.start_io()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run all Python tests**

```bash
$PY -m pytest server/tests -q
```
Expected: all pass (`test_server.py` is slow because each test starts a server and runs pyta). If a pytest-lsp test hangs on `wait_for_notification`, rerun with `-s` to see the server's stderr; a traceback there is the bug to fix.

- [ ] **Step 9: Commit**

```bash
git add server/pyta_lsp/scheduler.py server/pyta_lsp/server.py server/pyta_lsp/__main__.py server/tests/test_scheduler.py server/tests/test_server.py
git commit -m "feat(server): pygls language server with per-document scheduling"
```

---

### Task 6: Lockfile and bundle build

**Files:**
- Create: `server/requirements.in`, `server/requirements.lock` (generated), `scripts/bundle.py`, `THIRD_PARTY_NOTICES.md` (generated)
- Test: `server/tests/test_bundle_script.py`

**Interfaces:**
- Produces: `bundled/libs/` containing pure-Python `python_ta`, `pygls`, all dependencies, and `pyta_lsp`; `python scripts/bundle.py lock|build|verify`.
- In `scripts/bundle.py`: `read_pins(lock: Path) -> list[tuple[str, str]]` (name lowercased with `_` to `-`, markers and comments dropped, duplicates keep the highest version).

- [ ] **Step 1: Write `requirements.in` and the failing pin-parsing test**

`server/requirements.in`:
```
python-ta==2.13.1
pygls>=2.1,<3
```

`server/tests/test_bundle_script.py`:
```python
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bundle.py"


def _load():
    spec = importlib.util.spec_from_file_location("bundle", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_read_pins_strips_markers_comments_and_dedupes(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# comment\n"
        "Python_TA==2.13.1\n"
        "colorama==0.4.6 ; sys_platform == 'win32'\n"
        "tomli==2.0.1 ; python_full_version < '3.11'\n"
        "tomli==2.2.1 ; python_full_version >= '3.11'\n"
        "    # indented comment\n"
        "\n",
        encoding="utf-8",
    )
    bundle = _load()
    assert bundle.read_pins(lock) == [
        ("python-ta", "2.13.1"),
        ("colorama", "0.4.6"),
        ("tomli", "2.2.1"),
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
$PY -m pytest server/tests/test_bundle_script.py -q
```
Expected: FileNotFoundError because `scripts/bundle.py` does not exist.

- [ ] **Step 3: Implement `scripts/bundle.py`**

`scripts/bundle.py`:
```python
"""Build bundled/libs from server/requirements.lock using pure-Python packages only.

Usage:
  python scripts/bundle.py lock     # regenerate server/requirements.lock (universal, Python >= 3.10)
  python scripts/bundle.py build    # recreate bundled/libs and THIRD_PARTY_NOTICES.md, then verify
  python scripts/bundle.py verify   # import check against bundled/libs with an isolated interpreter
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from importlib.metadata import Distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
REQ_IN = SERVER / "requirements.in"
LOCK = SERVER / "requirements.lock"
LIBS = ROOT / "bundled" / "libs"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
MIN_PY = "3.10"
# No pure wheels on PyPI; built from sdist with extensions disabled.
SDIST_ONLY = {"aiohttp", "markupsafe"}
# Packages whose optional C speedups may compile during an sdist build; the binaries are deleted.
SPEEDUP_OK = {"markupsafe"}
COMPILED_SUFFIXES = (".so", ".pyd", ".dylib")
PURE_BUILD_ENV = {
    "AIOHTTP_NO_EXTENSIONS": "1",
    "MULTIDICT_NO_EXTENSIONS": "1",
    "YARL_NO_EXTENSIONS": "1",
    "FROZENLIST_NO_EXTENSIONS": "1",
    "PROPCACHE_NO_EXTENSIONS": "1",
}
_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)")


def run(cmd: list, **kwargs) -> None:
    printable = [str(c) for c in cmd]
    print("+", " ".join(printable), flush=True)
    subprocess.run(printable, check=True, **kwargs)


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", version))


def read_pins(lock: Path) -> list[tuple[str, str]]:
    pins: dict[str, str] = {}
    order: list[str] = []
    for raw in lock.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        match = _PIN.match(line)
        if not match:
            continue
        name = match.group(1).lower().replace("_", "-")
        version = match.group(2)
        if name not in pins:
            order.append(name)
            pins[name] = version
        elif _version_key(version) > _version_key(pins[name]):
            pins[name] = version
    return [(name, pins[name]) for name in order]


def cmd_lock() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        venv.create(tmp, with_pip=True)
        py = _venv_python(Path(tmp))
        run([py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "uv"])
        run([
            py, "-m", "uv", "pip", "compile", REQ_IN,
            "--universal", "--python-version", MIN_PY,
            "--no-header", "--no-annotate",
            "--output-file", LOCK,
        ])
    print(f"wrote {LOCK}")
    return 0


def _pip_target() -> list:
    return [
        sys.executable, "-m", "pip", "install",
        "--target", LIBS, "--no-deps", "--no-compile", "--disable-pip-version-check",
    ]


def strip_bundle() -> None:
    shutil.rmtree(LIBS / "bin", ignore_errors=True)
    offenders: list[Path] = []
    for path in sorted(LIBS.rglob("*"), reverse=True):
        if path.is_dir() and path.name == "__pycache__":
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file() and path.suffix in COMPILED_SUFFIXES:
            top = path.relative_to(LIBS).parts[0].lower()
            if top in SPEEDUP_OK:
                path.unlink()
            else:
                offenders.append(path)
    if offenders:
        names = ", ".join(str(p.relative_to(LIBS)) for p in offenders)
        raise SystemExit(f"compiled files in bundle (not allowed): {names}")


def write_notices() -> None:
    rows: list[tuple[str, str, str, str]] = []
    for info_dir in sorted(LIBS.glob("*.dist-info")):
        meta = Distribution.at(info_dir).metadata
        name = meta["Name"]
        version = meta["Version"]
        license_text = meta.get("License-Expression") or meta.get("License") or ""
        if not license_text or len(license_text) > 60:
            classifiers = [c for c in meta.get_all("Classifier", []) if c.startswith("License ::")]
            license_text = classifiers[-1].split("::")[-1].strip() if classifiers else (license_text[:57] + "...")
        homepage = meta.get("Home-page") or ""
        if not homepage:
            for url in meta.get_all("Project-URL", []):
                label, _, link = url.partition(",")
                if label.strip().lower() in ("homepage", "source", "repository"):
                    homepage = link.strip()
                    break
        rows.append((name, version, license_text, homepage))
    lines = [
        "# Third-party notices",
        "",
        "PythonTA Checker bundles the following unmodified Python packages inside the extension "
        "(`bundled/libs/`). Each package's license text ships in its `*.dist-info` directory in the bundle. "
        "The extension's own code is MIT licensed (see `LICENSE`).",
        "",
        "Generated by `scripts/bundle.py`; do not edit by hand.",
        "",
        "| Package | Version | License | Homepage |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {n} | {v} | {lic} | {home} |" for n, v, lic, home in rows]
    lines += [
        "",
        "Note: python-ta's wheel metadata declares MIT while the repository's LICENSE file is GPL-3.0; "
        "this project redistributes the wheel as published. See https://github.com/pyta-uoft/pyta.",
        "",
    ]
    NOTICES.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {NOTICES} ({len(rows)} packages)")


def cmd_verify() -> int:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "import python_ta, pygls, pyta_lsp, aiohttp, markupsafe, jinja2, pylint, astroid; "
        "assert python_ta.__file__.startswith(sys.argv[1]), python_ta.__file__; "
        "from importlib.metadata import version; "
        "print('bundle ok: python-ta', python_ta.__version__, '| pygls', version('pygls'))"
    )
    run([sys.executable, "-I", "-c", code, LIBS])
    return 0


def cmd_build() -> int:
    if not LOCK.exists():
        print("no lockfile; run `python scripts/bundle.py lock` first", file=sys.stderr)
        return 1
    if LIBS.exists():
        shutil.rmtree(LIBS)
    LIBS.mkdir(parents=True)
    pins = read_pins(LOCK)
    pure = [f"{n}=={v}" for n, v in pins if n not in SDIST_ONLY]
    sdist = [f"{n}=={v}" for n, v in pins if n in SDIST_ONLY]
    run(_pip_target() + [
        "--only-binary", ":all:", "--implementation", "py", "--python-version", MIN_PY,
        "--abi", "none", "--platform", "any", *pure,
    ])
    env = {**os.environ, **PURE_BUILD_ENV}
    for pin in sdist:
        run(_pip_target() + ["--no-binary", ":all:", pin], env=env)
    run(_pip_target() + [SERVER])
    strip_bundle()
    write_notices()
    return cmd_verify()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["lock", "build", "verify"])
    args = parser.parse_args(argv)
    return {"lock": cmd_lock, "build": cmd_build, "verify": cmd_verify}[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the pin test, then generate the lock and build the bundle**

```bash
$PY -m pytest server/tests/test_bundle_script.py -q
$PY scripts/bundle.py lock
$PY scripts/bundle.py build
```
Expected: `1 passed`; the lock step writes `server/requirements.lock` with `python-ta==2.13.1`, `pygls==2.1.x`, `aiohttp==3.14.x`, `markupsafe==3.x`, and marker-suffixed lines for conditional deps; the build step ends with `bundle ok: python-ta 2.13.1 | pygls 2.1.x`. Check size with `du -sh bundled/libs`; expect roughly 30 to 45 MB.

If the pure install fails because some pin has no `py3-none-any` wheel, that package goes into `SDIST_ONLY` only if it builds pure (add its `*_NO_EXTENSIONS` variable to `PURE_BUILD_ENV` if it has one); otherwise stop and report, since the bundle design depends on pure packages.

- [ ] **Step 5: Prove the bundle works with no python-ta installed**

```bash
python -m venv .venv-bare
BARE=.venv-bare/Scripts/python   # POSIX: .venv-bare/bin/python
$BARE -m pip install --quiet pytest pytest-asyncio packaging
$BARE -m pip install --quiet --no-deps pytest-lsp
PYTHONPATH="$(pwd)/bundled/libs" $BARE -m pytest server/tests -q -p no:cacheprovider
```
Expected: all tests pass using only the bundle (the runner subprocess inherits `PYTHONPATH`). Add `.venv-bare/` to `.gitignore`, then `rm -rf .venv-bare`.

- [ ] **Step 6: Commit**

```bash
git add server/requirements.in server/requirements.lock scripts/bundle.py THIRD_PARTY_NOTICES.md server/tests/test_bundle_script.py .gitignore
git commit -m "feat: build pure-Python bundle of python-ta, pygls and the server"
```

---

### Task 7: Extension scaffold, manifest, and pure helpers

**Files:**
- Create: `package.json`, `tsconfig.json`, `tsconfig.test.json`, `esbuild.mjs`, `eslint.config.mjs`, `vitest.config.mts`, `.vscodeignore`, `.vscode/launch.json`
- Create: `src/pythonVersion.ts`, `src/serverEnv.ts`, `src/extension.ts` (minimal)
- Test: `test/unit/pythonVersion.test.ts`, `test/unit/serverEnv.test.ts`

**Interfaces:**
- Produces:
  ```ts
  // src/pythonVersion.ts
  export const MIN_PYTHON: readonly [number, number];            // [3, 10]
  export const VERSION_PROBE: string;                            // python -c snippet printing "major.minor"
  export interface PythonVersion { major: number; minor: number }
  export function parsePythonVersion(output: string): PythonVersion | undefined
  export function isSupported(v: PythonVersion | undefined): v is PythonVersion
  export function formatVersion(v: PythonVersion): string
  // src/serverEnv.ts
  export type ImportStrategy = 'useBundled' | 'fromEnvironment';
  export function bundledLibsDir(extensionPath: string): string
  export function serverEnv(extensionPath: string, importStrategy: ImportStrategy, base?: NodeJS.ProcessEnv): NodeJS.ProcessEnv
  ```

- [ ] **Step 1: Write the manifest and tooling files**

`package.json`:
```json
{
  "name": "pyta-checker",
  "displayName": "PythonTA Checker",
  "description": "One-click PythonTA checks: see exactly what python_ta will flag, with PythonTA bundled in. No pip install needed.",
  "version": "0.1.0",
  "publisher": "ThePoNGz",
  "license": "MIT",
  "repository": { "type": "git", "url": "https://github.com/ThePoNGz/pyta-checker.git" },
  "bugs": { "url": "https://github.com/ThePoNGz/pyta-checker/issues" },
  "engines": { "vscode": "^1.101.0" },
  "categories": ["Linters", "Education"],
  "keywords": ["python", "pyta", "python_ta", "PythonTA", "linter", "uoft", "csc148", "csc108"],
  "activationEvents": ["onLanguage:python"],
  "extensionDependencies": ["ms-python.python"],
  "main": "./dist/extension.js",
  "contributes": {
    "commands": [
      { "command": "pythonta.check", "title": "Check Current File", "category": "PythonTA" },
      { "command": "pythonta.restart", "title": "Restart Server", "category": "PythonTA" },
      { "command": "pythonta.toggleOnlyPyta", "title": "Toggle Only-PythonTA Problems", "category": "PythonTA" },
      { "command": "pythonta.showOutput", "title": "Show Output Log", "category": "PythonTA" }
    ],
    "keybindings": [
      { "command": "pythonta.check", "key": "ctrl+alt+t", "mac": "cmd+alt+t", "when": "editorLangId == python" }
    ],
    "configuration": {
      "title": "PythonTA Checker",
      "properties": {
        "pythonta.runOnSave": {
          "type": "boolean",
          "default": true,
          "description": "Check a Python file each time it is saved."
        },
        "pythonta.runOnOpen": {
          "type": "boolean",
          "default": true,
          "description": "Check a Python file when it is opened."
        },
        "pythonta.configPath": {
          "type": "string",
          "default": "",
          "description": "PythonTA config file to use when a file has no embedded check_all(config=...). Relative paths resolve against the workspace folder."
        },
        "pythonta.importStrategy": {
          "type": "string",
          "enum": ["useBundled", "fromEnvironment"],
          "enumDescriptions": [
            "Use the PythonTA shipped inside the extension.",
            "Prefer the PythonTA installed in the selected interpreter; fall back to the bundled one."
          ],
          "default": "useBundled",
          "description": "Which PythonTA to run. Changing this restarts the server."
        },
        "pythonta.interpreter": {
          "type": "string",
          "default": "",
          "description": "Absolute path to a Python 3.10+ executable. Overrides the Python extension's selected interpreter. Changing this restarts the server."
        },
        "pythonta.hideOtherPythonDiagnostics": {
          "type": "boolean",
          "default": false,
          "description": "Hide Pylance and basedpyright problems so only PythonTA's show. Autocomplete keeps working. Toggle with the 'PythonTA: Toggle Only-PythonTA Problems' command."
        },
        "pythonta.trace.server": {
          "type": "string",
          "enum": ["off", "messages", "verbose"],
          "default": "off",
          "description": "Trace the communication between VS Code and the PythonTA language server."
        }
      }
    }
  },
  "scripts": {
    "check-types": "tsc --noEmit -p tsconfig.json && tsc --noEmit -p tsconfig.test.json",
    "lint": "eslint src test",
    "build": "node esbuild.mjs",
    "build:prod": "node esbuild.mjs --production",
    "watch": "node esbuild.mjs --watch",
    "compile-tests": "tsc -p tsconfig.test.json",
    "test:unit": "vitest run",
    "test:integration": "npm run build && npm run compile-tests && vscode-test",
    "test": "npm run check-types && npm run lint && npm run test:unit",
    "vscode:prepublish": "npm run build:prod",
    "package": "vsce package --no-dependencies"
  },
  "vsce": { "dependencies": false }
}
```

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "module": "Node16",
    "moduleResolution": "Node16",
    "target": "ES2022",
    "lib": ["ES2022"],
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "sourceMap": true,
    "noEmit": true,
    "types": ["node"]
  },
  "include": ["src"]
}
```

`tsconfig.test.json`:
```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "noEmit": false,
    "outDir": "out",
    "rootDir": ".",
    "types": ["node", "mocha"]
  },
  "include": ["src", "test/integration"]
}
```

`esbuild.mjs`:
```js
import * as esbuild from 'esbuild';

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

const ctx = await esbuild.context({
  entryPoints: ['src/extension.ts'],
  bundle: true,
  format: 'cjs',
  platform: 'node',
  target: 'node22',
  outfile: 'dist/extension.js',
  external: ['vscode'],
  minify: production,
  sourcemap: !production,
  sourcesContent: false,
  logLevel: 'info',
});

if (watch) {
  await ctx.watch();
} else {
  await ctx.rebuild();
  await ctx.dispose();
}
```

`eslint.config.mjs`:
```js
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist/**', 'out/**', 'node_modules/**', 'bundled/**', '.vscode-test/**'] },
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts', '**/*.mts'],
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
);
```

`vitest.config.mts`:
```ts
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/unit/**/*.test.ts'],
  },
});
```

`.vscodeignore`:
```
.vscode/**
.vscode-test/**
.vscode-test.mjs
.github/**
src/**
server/**
scripts/**
test/**
out/**
docs/**
node_modules/**
bundled/libs/**/__pycache__/**
.venv/**
.venv-bare/**
**/*.map
**/*.ts
esbuild.mjs
vitest.config.mts
tsconfig.json
tsconfig.test.json
eslint.config.mjs
.gitignore
.gitattributes
.editorconfig
*.vsix
```

`.vscode/launch.json` (for manual debugging in VS Code):
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run Extension",
      "type": "extensionHost",
      "request": "launch",
      "args": ["--extensionDevelopmentPath=${workspaceFolder}", "${workspaceFolder}/test/fixtures"],
      "outFiles": ["${workspaceFolder}/dist/**/*.js"],
      "preLaunchTask": "npm: build"
    }
  ]
}
```

- [ ] **Step 2: Install dependencies**

```bash
npm install --save vscode-languageclient@^10.1.1 @vscode/python-extension@^1.0.6
npm install --save-dev typescript@^5.9 @types/node@^22 @types/vscode@^1.101.0 esbuild eslint typescript-eslint vitest @vscode/test-cli @vscode/test-electron @vscode/vsce@^4 mocha @types/mocha
node -e "const p=require('./package.json');console.log(p.dependencies, Object.keys(p.devDependencies))"
```
Expected: `vscode-languageclient` resolves to a 10.x version; `package-lock.json` is created. Commit `package-lock.json` with the rest.

- [ ] **Step 3: Write the failing unit tests**

`test/unit/pythonVersion.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { formatVersion, isSupported, parsePythonVersion } from '../../src/pythonVersion';

describe('parsePythonVersion', () => {
  it('parses major.minor from probe output', () => {
    expect(parsePythonVersion('3.13\r\n')).toEqual({ major: 3, minor: 13 });
  });
  it('returns undefined for garbage', () => {
    expect(parsePythonVersion('')).toBeUndefined();
    expect(parsePythonVersion('Python was not found; run without arguments')).toBeUndefined();
  });
});

describe('isSupported', () => {
  it('accepts 3.10 and above', () => {
    expect(isSupported({ major: 3, minor: 10 })).toBe(true);
    expect(isSupported({ major: 3, minor: 14 })).toBe(true);
    expect(isSupported({ major: 4, minor: 0 })).toBe(true);
  });
  it('rejects older and undefined', () => {
    expect(isSupported({ major: 3, minor: 9 })).toBe(false);
    expect(isSupported({ major: 2, minor: 7 })).toBe(false);
    expect(isSupported(undefined)).toBe(false);
  });
});

describe('formatVersion', () => {
  it('formats as major.minor', () => {
    expect(formatVersion({ major: 3, minor: 12 })).toBe('3.12');
  });
});
```

`test/unit/serverEnv.test.ts`:
```ts
import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import { bundledLibsDir, serverEnv } from '../../src/serverEnv';

const EXT = path.join('C:', 'ext');

describe('serverEnv', () => {
  it('prepends bundled libs to PYTHONPATH and forces UTF-8', () => {
    const env = serverEnv(EXT, 'useBundled', { PATH: 'x', PYTHONPATH: 'existing' });
    const libs = bundledLibsDir(EXT);
    expect(env.PYTHONPATH).toBe(`${libs}${path.delimiter}existing`);
    expect(env.PYTHONIOENCODING).toBe('utf-8');
    expect(env.PYTHONUTF8).toBe('1');
    expect(env.PYTHONUNBUFFERED).toBe('1');
    expect(env.PYTA_LSP_LIBS).toBe(libs);
    expect(env.PYTA_LSP_IMPORT_STRATEGY).toBe('useBundled');
    expect(env.PATH).toBe('x');
  });
  it('sets PYTHONPATH to libs alone when none existed', () => {
    const env = serverEnv(EXT, 'fromEnvironment', {});
    expect(env.PYTHONPATH).toBe(bundledLibsDir(EXT));
    expect(env.PYTA_LSP_IMPORT_STRATEGY).toBe('fromEnvironment');
  });
});
```

- [ ] **Step 4: Run unit tests to verify they fail**

```bash
npm run test:unit
```
Expected: failures because `src/pythonVersion.ts` and `src/serverEnv.ts` do not exist.

- [ ] **Step 5: Implement the pure helpers and a minimal extension entry**

`src/pythonVersion.ts`:
```ts
export const MIN_PYTHON: readonly [number, number] = [3, 10];
export const VERSION_PROBE = "import sys; print('%d.%d' % sys.version_info[:2])";

export interface PythonVersion {
  major: number;
  minor: number;
}

export function parsePythonVersion(output: string): PythonVersion | undefined {
  const match = /^\s*(\d+)\.(\d+)\s*$/.exec(output);
  if (!match) {
    return undefined;
  }
  return { major: Number(match[1]), minor: Number(match[2]) };
}

export function isSupported(v: PythonVersion | undefined): v is PythonVersion {
  if (!v) {
    return false;
  }
  return v.major > MIN_PYTHON[0] || (v.major === MIN_PYTHON[0] && v.minor >= MIN_PYTHON[1]);
}

export function formatVersion(v: PythonVersion): string {
  return `${v.major}.${v.minor}`;
}
```

`src/serverEnv.ts`:
```ts
import * as path from 'node:path';

export type ImportStrategy = 'useBundled' | 'fromEnvironment';

export function bundledLibsDir(extensionPath: string): string {
  return path.join(extensionPath, 'bundled', 'libs');
}

export function serverEnv(
  extensionPath: string,
  importStrategy: ImportStrategy,
  base: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const libs = bundledLibsDir(extensionPath);
  return {
    ...base,
    PYTHONPATH: base.PYTHONPATH ? `${libs}${path.delimiter}${base.PYTHONPATH}` : libs,
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
    PYTA_LSP_LIBS: libs,
    PYTA_LSP_IMPORT_STRATEGY: importStrategy,
  };
}
```

`src/extension.ts` (minimal; expanded in Task 8):
```ts
import * as vscode from 'vscode';

let log: vscode.LogOutputChannel | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  log = vscode.window.createOutputChannel('PythonTA', { log: true });
  context.subscriptions.push(
    log,
    vscode.commands.registerCommand('pythonta.showOutput', () => log?.show(true)),
  );
  log.info('PythonTA Checker activated');
}

export async function deactivate(): Promise<void> {
  log = undefined;
}
```

- [ ] **Step 6: Run the checks**

```bash
npm run test:unit
npm run check-types
npm run lint
npm run build
ls dist
```
Expected: `7 passed` unit tests; type-check and lint clean; `dist/extension.js` exists. If `tsc -p tsconfig.test.json` complains that `test/integration` is empty, create `test/integration/.gitkeep` so the include is valid.

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json tsconfig.json tsconfig.test.json esbuild.mjs eslint.config.mjs vitest.config.mts .vscodeignore .vscode/launch.json src test/unit test/integration
git commit -m "feat(ext): extension scaffold with manifest, build tooling and pure helpers"
```

---

### Task 8: Interpreter discovery, language client, and server lifecycle

**Files:**
- Create: `src/settings.ts`, `src/pythonSelect.ts`, `src/python.ts`, `src/client.ts`
- Modify: `src/extension.ts`
- Test: `test/unit/pythonSelect.test.ts`

**Interfaces:**
- Consumes: `serverEnv`, `ImportStrategy` (Task 7), `parsePythonVersion`, `isSupported`, `VERSION_PROBE`, `formatVersion` (Task 7).
- Produces:
  ```ts
  // src/settings.ts
  export const SECTION = 'pythonta';
  export interface PytaSettings { runOnSave: boolean; runOnOpen: boolean; configPath: string; importStrategy: ImportStrategy; interpreter: string; hideOtherPythonDiagnostics: boolean }
  export function getSettings(): PytaSettings
  export function serverSettings(s: PytaSettings): { runOnSave: boolean; runOnOpen: boolean; configPath: string }
  // src/pythonSelect.ts
  export type Origin = 'setting' | 'python-extension' | 'path';
  export interface Candidate { path: string; origin: Origin }
  export interface PythonInfo { path: string; version: PythonVersion; origin: Origin }
  export type Probe = (command: string, args: string[]) => Promise<string>;
  export function selectPython(candidates: Candidate[], probe: Probe): Promise<PythonInfo | { error: string }>
  export function pathCandidates(platform: NodeJS.Platform): Candidate[]
  // src/python.ts
  export function findPython(settingPath: string, log: vscode.LogOutputChannel): Promise<PythonInfo | { error: string }>
  export function onInterpreterChanged(listener: () => void, log: vscode.LogOutputChannel): Promise<vscode.Disposable | undefined>
  // src/client.ts
  export const STATUS_NOTIFICATION = 'pyta/status'; export const CHECK_COMMAND = 'pyta.check';
  export interface StatusParams { uri: string; state: 'checking' | 'done'; count: number | null }
  export function createClient(pythonPath: string, extensionPath: string, log: vscode.LogOutputChannel): LanguageClient
  export function requestCheck(client: LanguageClient, uri: vscode.Uri): Promise<void>
  ```

- [ ] **Step 1: Write the failing selection tests**

`test/unit/pythonSelect.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { pathCandidates, selectPython, type Candidate, type Probe } from '../../src/pythonSelect';

function fakeProbe(table: Record<string, string | Error>): Probe {
  return async (command) => {
    const result = table[command];
    if (result === undefined || result instanceof Error) {
      throw result ?? new Error(`spawn ${command} ENOENT`);
    }
    return result;
  };
}

describe('selectPython', () => {
  it('returns the first candidate that is 3.10 or newer, in order', async () => {
    const candidates: Candidate[] = [
      { path: 'C:/old/python.exe', origin: 'setting' },
      { path: 'C:/good/python.exe', origin: 'python-extension' },
      { path: 'python', origin: 'path' },
    ];
    const result = await selectPython(
      candidates,
      fakeProbe({ 'C:/old/python.exe': '3.9\n', 'C:/good/python.exe': '3.13\n', python: '3.14\n' }),
    );
    expect(result).toEqual({ path: 'C:/good/python.exe', version: { major: 3, minor: 13 }, origin: 'python-extension' });
  });

  it('skips candidates that fail to run', async () => {
    const result = await selectPython(
      [{ path: 'python', origin: 'path' }, { path: 'python3', origin: 'path' }],
      fakeProbe({ python: new Error('ENOENT'), python3: '3.12' }),
    );
    expect(result).toMatchObject({ path: 'python3' });
  });

  it('reports every attempt when nothing qualifies', async () => {
    const result = await selectPython(
      [{ path: 'py', origin: 'path' }, { path: 'python', origin: 'path' }],
      fakeProbe({ py: '3.8\n', python: new Error('ENOENT') }),
    );
    expect(result).toHaveProperty('error');
    const error = (result as { error: string }).error;
    expect(error).toContain('py (Python 3.8, too old)');
    expect(error).toContain('python (not runnable)');
  });
});

describe('pathCandidates', () => {
  it('prefers py launcher last on windows and python3 first elsewhere', () => {
    expect(pathCandidates('win32').map((c) => c.path)).toEqual(['python', 'python3', 'py']);
    expect(pathCandidates('linux').map((c) => c.path)).toEqual(['python3', 'python']);
    expect(pathCandidates('darwin').map((c) => c.path)).toEqual(['python3', 'python']);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test:unit
```
Expected: failure because `src/pythonSelect.ts` does not exist.

- [ ] **Step 3: Implement settings, selection, discovery, and the client**

`src/settings.ts`:
```ts
import * as vscode from 'vscode';
import type { ImportStrategy } from './serverEnv';

export const SECTION = 'pythonta';

export interface PytaSettings {
  runOnSave: boolean;
  runOnOpen: boolean;
  configPath: string;
  importStrategy: ImportStrategy;
  interpreter: string;
  hideOtherPythonDiagnostics: boolean;
}

export function getSettings(): PytaSettings {
  const config = vscode.workspace.getConfiguration(SECTION);
  const strategy = config.get<string>('importStrategy', 'useBundled');
  return {
    runOnSave: config.get<boolean>('runOnSave', true),
    runOnOpen: config.get<boolean>('runOnOpen', true),
    configPath: config.get<string>('configPath', ''),
    importStrategy: strategy === 'fromEnvironment' ? 'fromEnvironment' : 'useBundled',
    interpreter: config.get<string>('interpreter', ''),
    hideOtherPythonDiagnostics: config.get<boolean>('hideOtherPythonDiagnostics', false),
  };
}

export function serverSettings(s: PytaSettings): { runOnSave: boolean; runOnOpen: boolean; configPath: string } {
  return { runOnSave: s.runOnSave, runOnOpen: s.runOnOpen, configPath: s.configPath };
}
```

`src/pythonSelect.ts`:
```ts
import { MIN_PYTHON, VERSION_PROBE, formatVersion, isSupported, parsePythonVersion, type PythonVersion } from './pythonVersion';

export type Origin = 'setting' | 'python-extension' | 'path';

export interface Candidate {
  path: string;
  origin: Origin;
}

export interface PythonInfo {
  path: string;
  version: PythonVersion;
  origin: Origin;
}

export type Probe = (command: string, args: string[]) => Promise<string>;

export function pathCandidates(platform: NodeJS.Platform): Candidate[] {
  const names = platform === 'win32' ? ['python', 'python3', 'py'] : ['python3', 'python'];
  return names.map((path) => ({ path, origin: 'path' as const }));
}

export async function selectPython(candidates: Candidate[], probe: Probe): Promise<PythonInfo | { error: string }> {
  const attempts: string[] = [];
  for (const candidate of candidates) {
    let version: PythonVersion | undefined;
    try {
      version = parsePythonVersion(await probe(candidate.path, ['-c', VERSION_PROBE]));
    } catch {
      version = undefined;
    }
    if (isSupported(version)) {
      return { path: candidate.path, version, origin: candidate.origin };
    }
    attempts.push(version ? `${candidate.path} (Python ${formatVersion(version)}, too old)` : `${candidate.path} (not runnable)`);
  }
  return {
    error: `No Python ${MIN_PYTHON[0]}.${MIN_PYTHON[1]} or newer was found. Tried: ${attempts.join('; ') || 'nothing'}`,
  };
}
```

`src/python.ts`:
```ts
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { PythonExtension } from '@vscode/python-extension';
import * as vscode from 'vscode';
import { formatVersion } from './pythonVersion';
import { pathCandidates, selectPython, type Candidate, type Probe, type PythonInfo } from './pythonSelect';

const execFileAsync = promisify(execFile);

const defaultProbe: Probe = async (command, args) => {
  const { stdout } = await execFileAsync(command, args, { timeout: 15_000, windowsHide: true });
  return stdout;
};

async function pythonExtensionCandidate(log: vscode.LogOutputChannel): Promise<Candidate | undefined> {
  try {
    const api = await PythonExtension.api();
    const active = api.environments.getActiveEnvironmentPath();
    const resolved = await api.environments.resolveEnvironment(active);
    const executable = resolved?.executable.uri?.fsPath;
    if (executable) {
      return { path: executable, origin: 'python-extension' };
    }
    log.warn(`Python extension has no runnable interpreter for ${active.path}`);
  } catch (error) {
    log.warn(`Python extension API unavailable: ${String(error)}`);
  }
  return undefined;
}

export async function findPython(settingPath: string, log: vscode.LogOutputChannel): Promise<PythonInfo | { error: string }> {
  const candidates: Candidate[] = [];
  if (settingPath) {
    candidates.push({ path: settingPath, origin: 'setting' });
  }
  const fromExtension = await pythonExtensionCandidate(log);
  if (fromExtension) {
    candidates.push(fromExtension);
  }
  candidates.push(...pathCandidates(process.platform));
  const result = await selectPython(candidates, defaultProbe);
  if ('error' in result) {
    log.error(result.error);
  } else {
    log.info(`Using Python ${formatVersion(result.version)} at ${result.path} (${result.origin})`);
  }
  return result;
}

export async function onInterpreterChanged(
  listener: () => void,
  log: vscode.LogOutputChannel,
): Promise<vscode.Disposable | undefined> {
  try {
    const api = await PythonExtension.api();
    return api.environments.onDidChangeActiveEnvironmentPath(() => listener());
  } catch (error) {
    log.warn(`Cannot watch interpreter changes: ${String(error)}`);
    return undefined;
  }
}
```

`src/client.ts`:
```ts
import * as vscode from 'vscode';
import {
  ExecuteCommandRequest,
  LanguageClient,
  TransportKind,
  type LanguageClientOptions,
  type ServerOptions,
} from 'vscode-languageclient/node';
import { serverEnv } from './serverEnv';
import { SECTION, getSettings, serverSettings } from './settings';

export const STATUS_NOTIFICATION = 'pyta/status';
export const CHECK_COMMAND = 'pyta.check';

export interface StatusParams {
  uri: string;
  state: 'checking' | 'done';
  count: number | null;
}

export function createClient(pythonPath: string, extensionPath: string, log: vscode.LogOutputChannel): LanguageClient {
  const settings = getSettings();
  const serverOptions: ServerOptions = {
    command: pythonPath,
    args: ['-m', 'pyta_lsp'],
    transport: TransportKind.stdio,
    options: { cwd: extensionPath, env: serverEnv(extensionPath, settings.importStrategy) },
  };
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: 'file', language: 'python' }],
    outputChannel: log,
    diagnosticCollectionName: 'PythonTA',
    initializationOptions: () => serverSettings(getSettings()),
    synchronize: { configurationSection: SECTION },
  };
  return new LanguageClient(SECTION, 'PythonTA', serverOptions, clientOptions);
}

export async function requestCheck(client: LanguageClient, uri: vscode.Uri): Promise<void> {
  await client.sendRequest(ExecuteCommandRequest.type, {
    command: CHECK_COMMAND,
    arguments: [client.code2ProtocolConverter.asUri(uri)],
  });
}
```

- [ ] **Step 4: Wire the lifecycle into `src/extension.ts`**

Replace `src/extension.ts` with:
```ts
import * as vscode from 'vscode';
import type { LanguageClient } from 'vscode-languageclient/node';
import { createClient, requestCheck } from './client';
import { findPython, onInterpreterChanged } from './python';
import { getSettings } from './settings';

let client: LanguageClient | undefined;
let log: vscode.LogOutputChannel;
let restarting: Promise<void> | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  log = vscode.window.createOutputChannel('PythonTA', { log: true });
  context.subscriptions.push(
    log,
    vscode.commands.registerCommand('pythonta.showOutput', () => log.show(true)),
    vscode.commands.registerCommand('pythonta.restart', () => restartServer(context)),
    vscode.commands.registerCommand('pythonta.check', () => checkActiveFile()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration('pythonta.interpreter') || event.affectsConfiguration('pythonta.importStrategy')) {
        void restartServer(context);
      }
    }),
  );
  await startServer(context);
  const watcher = await onInterpreterChanged(() => {
    log.info('Python interpreter changed; restarting PythonTA server');
    void restartServer(context);
  }, log);
  if (watcher) {
    context.subscriptions.push(watcher);
  }
}

export async function deactivate(): Promise<void> {
  await stopServer();
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
  const settings = getSettings();
  const python = await findPython(settings.interpreter, log);
  if ('error' in python) {
    showPythonError(python.error);
    return;
  }
  const next = createClient(python.path, context.extensionPath, log);
  client = next;
  try {
    await next.start();
    log.info('PythonTA server started');
  } catch (error) {
    log.error(`PythonTA server failed to start: ${String(error)}`);
    void vscode.window.showErrorMessage('PythonTA server failed to start.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
  }
}

async function stopServer(): Promise<void> {
  const current = client;
  client = undefined;
  if (current) {
    try {
      await current.stop();
    } catch (error) {
      log.warn(`Error stopping PythonTA server: ${String(error)}`);
    }
  }
}

async function restartServer(context: vscode.ExtensionContext): Promise<void> {
  if (restarting) {
    return restarting;
  }
  restarting = (async () => {
    await stopServer();
    await startServer(context);
  })();
  try {
    await restarting;
  } finally {
    restarting = undefined;
  }
}

async function checkActiveFile(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== 'python' || editor.document.uri.scheme !== 'file') {
    void vscode.window.showInformationMessage('PythonTA: open a saved Python file first.');
    return;
  }
  if (editor.document.isDirty) {
    await editor.document.save();
  }
  if (!client?.isRunning()) {
    void vscode.window.showWarningMessage('PythonTA server is not running.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
    return;
  }
  await requestCheck(client, editor.document.uri);
}

function showPythonError(message: string): void {
  void vscode.window
    .showErrorMessage(`PythonTA: ${message}`, 'Select Interpreter', 'How to install Python')
    .then((choice) => {
      if (choice === 'Select Interpreter') {
        void vscode.commands.executeCommand('python.setInterpreter');
      } else if (choice === 'How to install Python') {
        void vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/'));
      }
    });
}
```

- [ ] **Step 5: Run checks and try it by hand**

```bash
npm run test:unit
npm run check-types
npm run lint
npm run build
```
Expected: unit tests pass (`11 passed`), type-check and lint clean.

Manual smoke test (requires `bundled/libs` from Task 6): open the repo in VS Code, press F5 (the "Run Extension" launch config opens `test/fixtures`), open `course_style.py`. Expect PythonTA squiggles within a few seconds, "PythonTA" in the Output panel dropdown with "PythonTA server started", and no `E9999`.

- [ ] **Step 6: Commit**

```bash
git add src test/unit
git commit -m "feat(ext): discover the interpreter and run the PythonTA language server"
```

---

### Task 9: Status bar

**Files:**
- Create: `src/statusBar.ts`
- Modify: `src/extension.ts`, `src/client.ts` (no interface change; register the notification handler)

**Interfaces:**
- Consumes: `STATUS_NOTIFICATION`, `StatusParams` (Task 8).
- Produces:
  ```ts
  export type ServerState = 'starting' | 'running' | 'error';
  export class StatusBar implements vscode.Disposable {
    constructor();
    setServerState(state: ServerState): void;
    onStatus(params: StatusParams): void;
    refresh(): void;
    dispose(): void;
  }
  ```

- [ ] **Step 1: Implement `src/statusBar.ts`**

```ts
import * as vscode from 'vscode';
import type { StatusParams } from './client';

export type ServerState = 'starting' | 'running' | 'error';

interface FileStatus {
  state: 'checking' | 'done';
  count: number;
}

export class StatusBar implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;
  private readonly files = new Map<string, FileStatus>();
  private serverState: ServerState = 'starting';
  private readonly subscriptions: vscode.Disposable[] = [];

  constructor() {
    this.item = vscode.window.createStatusBarItem('pythonta.status', vscode.StatusBarAlignment.Right, 90);
    this.item.name = 'PythonTA';
    this.subscriptions.push(
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()),
      vscode.workspace.onDidCloseTextDocument((doc) => {
        this.files.delete(doc.uri.toString());
        this.refresh();
      }),
    );
    this.item.show();
    this.refresh();
  }

  setServerState(state: ServerState): void {
    this.serverState = state;
    this.refresh();
  }

  onStatus(params: StatusParams): void {
    this.files.set(vscode.Uri.parse(params.uri).toString(), { state: params.state, count: params.count ?? 0 });
    this.refresh();
  }

  refresh(): void {
    if (this.serverState === 'error') {
      this.set('$(error) PyTA', 'PythonTA server is not running. Click to show the log.', 'pythonta.showOutput', true);
      return;
    }
    if (this.serverState === 'starting') {
      this.set('$(sync~spin) PyTA', 'PythonTA server is starting', 'pythonta.showOutput', false);
      return;
    }
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== 'python') {
      this.set('PyTA', 'PythonTA Checker: open a Python file', 'pythonta.check', false);
      return;
    }
    const status = this.files.get(editor.document.uri.toString());
    if (!status) {
      this.set('PyTA', 'PythonTA: click to check this file', 'pythonta.check', false);
    } else if (status.state === 'checking') {
      this.set('$(sync~spin) PyTA', 'PythonTA is checking this file', 'pythonta.check', false);
    } else if (status.count === 0) {
      this.set('$(check) PyTA', 'PythonTA found no problems in this file. Click to re-check.', 'pythonta.check', false);
    } else {
      this.set(
        `$(warning) PyTA ${status.count}`,
        `PythonTA found ${status.count} problem${status.count === 1 ? '' : 's'} in this file. Click to re-check.`,
        'pythonta.check',
        false,
      );
    }
  }

  private set(text: string, tooltip: string, command: string, warn: boolean): void {
    this.item.text = text;
    this.item.tooltip = tooltip;
    this.item.command = command;
    this.item.backgroundColor = warn ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
  }

  dispose(): void {
    this.item.dispose();
    for (const sub of this.subscriptions) {
      sub.dispose();
    }
  }
}
```

- [ ] **Step 2: Wire it in `src/extension.ts`**

Add near the other module-level variables:
```ts
import { State } from 'vscode-languageclient/node';
import { STATUS_NOTIFICATION, type StatusParams } from './client';
import { StatusBar } from './statusBar';

let statusBar: StatusBar;
```
(Change the existing `import type { LanguageClient }` line to `import { State, type LanguageClient } from 'vscode-languageclient/node';` instead of adding a second import from the same module.)

In `activate`, right after creating `log`:
```ts
  statusBar = new StatusBar();
  context.subscriptions.push(statusBar);
```

In `startServer`, replace the block from `const next = createClient(...)` to the end of the function with:
```ts
  const next = createClient(python.path, context.extensionPath, log);
  client = next;
  statusBar.setServerState('starting');
  next.onNotification(STATUS_NOTIFICATION, (params: StatusParams) => statusBar.onStatus(params));
  next.onDidChangeState((event) => {
    if (client !== next) {
      return;
    }
    if (event.newState === State.Running) {
      statusBar.setServerState('running');
    } else if (event.newState === State.StartFailed || event.newState === State.Stopped) {
      statusBar.setServerState('error');
    }
  });
  try {
    await next.start();
    log.info('PythonTA server started');
  } catch (error) {
    statusBar.setServerState('error');
    log.error(`PythonTA server failed to start: ${String(error)}`);
    void vscode.window.showErrorMessage('PythonTA server failed to start.', 'Show Output').then((choice) => {
      if (choice) {
        log.show(true);
      }
    });
  }
```

In `startServer`, in the `if ('error' in python)` branch, add `statusBar.setServerState('error');` before `showPythonError(...)`.

- [ ] **Step 3: Verify**

```bash
npm run check-types && npm run lint && npm run build
```
Expected: clean. Manual: F5, open `course_style.py`; the status bar shows a spinner then `PyTA 3` (or the count pyta reports); open `clean.py` and it shows a check mark; click it to re-check.

- [ ] **Step 4: Commit**

```bash
git add src
git commit -m "feat(ext): status bar showing server and per-file check state"
```

---

### Task 10: Only-PythonTA mode

**Files:**
- Create: `src/onlyPytaLogic.ts`, `src/onlyPyta.ts`
- Modify: `src/extension.ts`
- Test: `test/unit/onlyPytaLogic.test.ts`

**Interfaces:**
- Produces:
  ```ts
  // src/onlyPytaLogic.ts
  export const IGNORE_ALL: readonly string[];              // ['**']
  export interface Target { section: string; key: string; restartCommand: string }
  export const TARGETS: readonly Target[];                  // python + basedpyright
  export type Snapshot = Record<string, unknown>;           // section -> previous global value; null means "was absent"
  export interface Write { section: string; key: string; value: unknown }   // value undefined removes the key
  export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] }
  export function planDisable(saved: Snapshot | undefined): Write[]
  // src/onlyPyta.ts
  export const SAVED_KEY = 'pythonta.savedIgnore'; export const PROMPTED_KEY = 'pythonta.promptedOnlyPyta';
  export function maybePromptFirstRun(context: vscode.ExtensionContext): Promise<void>
  export function applyOnlyPyta(enabled: boolean, context: vscode.ExtensionContext, log: vscode.LogOutputChannel): Promise<void>
  export function toggleOnlyPyta(): Promise<void>
  ```

- [ ] **Step 1: Write the failing logic tests**

`test/unit/onlyPytaLogic.test.ts`:
```ts
import { describe, expect, it } from 'vitest';
import { IGNORE_ALL, TARGETS, planDisable, planEnable } from '../../src/onlyPytaLogic';

describe('TARGETS', () => {
  it('covers pylance (via the python extension) and basedpyright with verified command ids', () => {
    expect(TARGETS).toEqual([
      { section: 'python', key: 'analysis.ignore', restartCommand: 'python.analysis.restartLanguageServer' },
      { section: 'basedpyright', key: 'analysis.ignore', restartCommand: 'basedpyright.restartserver' },
    ]);
  });
});

describe('planEnable', () => {
  it('snapshots current values the first time and writes ignore-all to both', () => {
    const plan = planEnable({ python: ['src/generated'], basedpyright: null }, undefined);
    expect(plan.saved).toEqual({ python: ['src/generated'], basedpyright: null });
    expect(plan.writes).toEqual([
      { section: 'python', key: 'analysis.ignore', value: IGNORE_ALL },
      { section: 'basedpyright', key: 'analysis.ignore', value: IGNORE_ALL },
    ]);
  });

  it('keeps an existing snapshot so re-enabling never saves our own ignore-all', () => {
    const plan = planEnable({ python: IGNORE_ALL, basedpyright: IGNORE_ALL }, { python: null, basedpyright: ['x'] });
    expect(plan.saved).toEqual({ python: null, basedpyright: ['x'] });
  });
});

describe('planDisable', () => {
  it('restores saved values and removes keys that were absent', () => {
    expect(planDisable({ python: ['src/generated'], basedpyright: null })).toEqual([
      { section: 'python', key: 'analysis.ignore', value: ['src/generated'] },
      { section: 'basedpyright', key: 'analysis.ignore', value: undefined },
    ]);
  });

  it('writes nothing when there is no snapshot', () => {
    expect(planDisable(undefined)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
npm run test:unit
```
Expected: failure because `src/onlyPytaLogic.ts` does not exist.

- [ ] **Step 3: Implement the logic and the VS Code glue**

`src/onlyPytaLogic.ts`:
```ts
export const IGNORE_ALL: readonly string[] = ['**'];

export interface Target {
  section: string;
  key: string;
  restartCommand: string;
}

export const TARGETS: readonly Target[] = [
  { section: 'python', key: 'analysis.ignore', restartCommand: 'python.analysis.restartLanguageServer' },
  { section: 'basedpyright', key: 'analysis.ignore', restartCommand: 'basedpyright.restartserver' },
];

export type Snapshot = Record<string, unknown>;

export interface Write {
  section: string;
  key: string;
  value: unknown;
}

export function planEnable(current: Snapshot, saved: Snapshot | undefined): { saved: Snapshot; writes: Write[] } {
  return {
    saved: saved ?? current,
    writes: TARGETS.map((t) => ({ section: t.section, key: t.key, value: IGNORE_ALL })),
  };
}

export function planDisable(saved: Snapshot | undefined): Write[] {
  if (!saved) {
    return [];
  }
  return TARGETS.map((t) => {
    const previous = saved[t.section];
    return { section: t.section, key: t.key, value: previous === null ? undefined : previous };
  });
}
```

`src/onlyPyta.ts`:
```ts
import * as vscode from 'vscode';
import { TARGETS, planDisable, planEnable, type Snapshot, type Write } from './onlyPytaLogic';
import { SECTION } from './settings';

export const SAVED_KEY = 'pythonta.savedIgnore';
export const PROMPTED_KEY = 'pythonta.promptedOnlyPyta';
const SETTING = 'hideOtherPythonDiagnostics';

export async function maybePromptFirstRun(context: vscode.ExtensionContext): Promise<void> {
  if (context.globalState.get<boolean>(PROMPTED_KEY) || process.env.PYTA_SKIP_PROMPT) {
    return;
  }
  await context.globalState.update(PROMPTED_KEY, true);
  const choice = await vscode.window.showInformationMessage(
    "PythonTA Checker: hide Pylance and basedpyright problems so only PythonTA's show? Autocomplete keeps working. Change it later with 'PythonTA: Toggle Only-PythonTA Problems'.",
    'Yes',
    'No',
  );
  if (choice === 'Yes') {
    await vscode.workspace.getConfiguration(SECTION).update(SETTING, true, vscode.ConfigurationTarget.Global);
  }
}

export async function applyOnlyPyta(
  enabled: boolean,
  context: vscode.ExtensionContext,
  log: vscode.LogOutputChannel,
): Promise<void> {
  const saved = context.globalState.get<Snapshot>(SAVED_KEY);
  let writes: Write[];
  if (enabled) {
    const current: Snapshot = {};
    for (const target of TARGETS) {
      const inspected = vscode.workspace.getConfiguration(target.section).inspect<unknown>(target.key);
      current[target.section] = inspected?.globalValue === undefined ? null : inspected.globalValue;
    }
    const plan = planEnable(current, saved);
    await context.globalState.update(SAVED_KEY, plan.saved);
    writes = plan.writes;
  } else {
    writes = planDisable(saved);
    await context.globalState.update(SAVED_KEY, undefined);
  }
  for (const write of writes) {
    try {
      await vscode.workspace.getConfiguration(write.section).update(write.key, write.value, vscode.ConfigurationTarget.Global);
      log.info(`${enabled ? 'Set' : 'Restored'} ${write.section}.${write.key}`);
    } catch (error) {
      log.info(`Skipping ${write.section}.${write.key} (extension not installed?): ${String(error)}`);
    }
  }
  await restartOtherServers(log);
}

async function restartOtherServers(log: vscode.LogOutputChannel): Promise<void> {
  const ids = new Set(await vscode.commands.getCommands(true));
  for (const target of TARGETS) {
    if (!ids.has(target.restartCommand)) {
      continue;
    }
    try {
      await vscode.commands.executeCommand(target.restartCommand);
    } catch (error) {
      log.warn(`Could not run ${target.restartCommand}: ${String(error)}`);
    }
  }
}

export async function toggleOnlyPyta(): Promise<void> {
  const config = vscode.workspace.getConfiguration(SECTION);
  const current = config.get<boolean>(SETTING, false);
  await config.update(SETTING, !current, vscode.ConfigurationTarget.Global);
  void vscode.window.showInformationMessage(
    current ? 'PythonTA: other Python problems are visible again.' : 'PythonTA: showing only PythonTA problems.',
  );
}
```

- [ ] **Step 4: Wire into `src/extension.ts`**

Add the import:
```ts
import { SAVED_KEY, applyOnlyPyta, maybePromptFirstRun, toggleOnlyPyta } from './onlyPyta';
```

In `activate`, add to the `context.subscriptions.push(...)` list:
```ts
    vscode.commands.registerCommand('pythonta.toggleOnlyPyta', () => toggleOnlyPyta()),
```
and extend the existing `onDidChangeConfiguration` handler with:
```ts
      if (event.affectsConfiguration('pythonta.hideOtherPythonDiagnostics')) {
        void applyOnlyPyta(getSettings().hideOtherPythonDiagnostics, context, log);
      }
```

After `await startServer(context);` add:
```ts
  const settings = getSettings();
  if (settings.hideOtherPythonDiagnostics || context.globalState.get(SAVED_KEY)) {
    await applyOnlyPyta(settings.hideOtherPythonDiagnostics, context, log);
  }
  void maybePromptFirstRun(context);
```

- [ ] **Step 5: Verify**

```bash
npm run test:unit
npm run check-types
npm run lint
npm run build
```
Expected: `15 passed` unit tests, everything else clean. Manual: F5, answer "Yes" to the prompt; Pylance squiggles disappear from `course_style.py` while PythonTA's stay; run "PythonTA: Toggle Only-PythonTA Problems" and they come back; user `settings.json` shows `python.analysis.ignore` only while enabled.

- [ ] **Step 6: Commit**

```bash
git add src test/unit
git commit -m "feat(ext): opt-in mode that hides Pylance and basedpyright diagnostics"
```

---

### Task 11: VS Code integration test

**Files:**
- Create: `.vscode-test.mjs`, `test/integration/helpers.ts`, `test/integration/extension.test.ts`
- Remove: `test/integration/.gitkeep` if it exists

**Interfaces:**
- Consumes: the built extension (`dist/extension.js`), `bundled/libs` (Task 6), fixtures (Task 2).
- Produces: `npm run test:integration` passing on a machine with any Python 3.10+ on PATH.

- [ ] **Step 1: Write the test config and helper**

`.vscode-test.mjs`:
```js
import { defineConfig } from '@vscode/test-cli';
import path from 'node:path';

export default defineConfig({
  label: 'integration',
  files: 'out/test/integration/**/*.test.js',
  version: 'stable',
  workspaceFolder: path.resolve('test/fixtures'),
  launchArgs: ['--disable-gpu'],
  env: { PYTA_SKIP_PROMPT: '1' },
  mocha: { ui: 'tdd', timeout: 180_000, color: true },
});
```

`test/integration/helpers.ts`:
```ts
import * as vscode from 'vscode';

export const SOURCE = 'PythonTA';

export function codeOf(diagnostic: vscode.Diagnostic): string {
  const code = diagnostic.code;
  if (code && typeof code === 'object') {
    return String(code.value);
  }
  return String(code ?? '');
}

export function pytaDiagnostics(uri: vscode.Uri): vscode.Diagnostic[] {
  return vscode.languages.getDiagnostics(uri).filter((d) => d.source === SOURCE);
}

export function waitForPytaDiagnostics(
  uri: vscode.Uri,
  predicate: (diagnostics: vscode.Diagnostic[]) => boolean,
  timeoutMs = 120_000,
): Promise<vscode.Diagnostic[]> {
  return new Promise((resolve, reject) => {
    const check = (): boolean => {
      const diagnostics = pytaDiagnostics(uri);
      if (predicate(diagnostics)) {
        cleanup();
        resolve(diagnostics);
        return true;
      }
      return false;
    };
    const subscription = vscode.languages.onDidChangeDiagnostics((event) => {
      if (event.uris.some((u) => u.toString() === uri.toString())) {
        check();
      }
    });
    const timer = setTimeout(() => {
      cleanup();
      const last = pytaDiagnostics(uri).map((d) => `${codeOf(d)}: ${d.message}`);
      reject(new Error(`timed out waiting for PythonTA diagnostics on ${uri.fsPath}; last: ${JSON.stringify(last)}`));
    }, timeoutMs);
    function cleanup(): void {
      clearTimeout(timer);
      subscription.dispose();
    }
    check();
  });
}

export function waitForDiagnosticsChange(uri: vscode.Uri, timeoutMs = 120_000): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      subscription.dispose();
      reject(new Error(`timed out waiting for a diagnostics change on ${uri.fsPath}`));
    }, timeoutMs);
    const subscription = vscode.languages.onDidChangeDiagnostics((event) => {
      if (event.uris.some((u) => u.toString() === uri.toString())) {
        clearTimeout(timer);
        subscription.dispose();
        resolve();
      }
    });
  });
}

export async function openFixture(name: string): Promise<vscode.Uri> {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    throw new Error('no workspace folder; .vscode-test.mjs must set workspaceFolder');
  }
  const uri = vscode.Uri.joinPath(folder.uri, name);
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document);
  return uri;
}
```

- [ ] **Step 2: Write the tests**

`test/integration/extension.test.ts`:
```ts
import * as assert from 'node:assert';
import * as vscode from 'vscode';
import { codeOf, openFixture, pytaDiagnostics, waitForDiagnosticsChange, waitForPytaDiagnostics } from './helpers';

suite('PythonTA Checker', () => {
  suiteSetup(async () => {
    const extension = vscode.extensions.getExtension('ThePoNGz.pyta-checker');
    assert.ok(extension, 'extension not found; check publisher/name in package.json');
    await extension.activate();
  });

  test('honors the embedded check_all config', async () => {
    const uri = await openFixture('course_style.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.length > 0);
    const codes = diagnostics.map(codeOf);
    assert.ok(codes.includes('E9989'), `expected E9989 in ${codes}`);
    assert.ok(!codes.includes('E9999'), `E9999 must not appear when extra-imports allows random: ${codes}`);
    assert.ok(!codes.includes('E9998'), `E9998 must not appear when allowed-io allows roll: ${codes}`);
    const pep8 = diagnostics.find((d) => codeOf(d) === 'E9989');
    assert.ok(pep8);
    assert.strictEqual(pep8.severity, vscode.DiagnosticSeverity.Error);
    assert.strictEqual(pep8.range.start.line, 11);
    const code = pep8.code;
    assert.ok(code && typeof code === 'object', 'code should carry a docs link');
    assert.ok(code.target.toString().endsWith('#e9989'), code.target.toString());
  });

  test('reports forbidden imports when there is no embedded config', async () => {
    const uri = await openFixture('no_config.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.some((x) => codeOf(x) === 'E9999'));
    assert.ok(diagnostics.length > 0);
  });

  test('reports a syntax error as E0001', async () => {
    const uri = await openFixture('syntax_error.py');
    const diagnostics = await waitForPytaDiagnostics(uri, (d) => d.length > 0);
    assert.deepStrictEqual(diagnostics.map(codeOf), ['E0001']);
    assert.strictEqual(diagnostics[0].range.start.line, 3);
  });

  test('the check command re-runs on the active file', async () => {
    const uri = await openFixture('no_config.py');
    await waitForPytaDiagnostics(uri, (d) => d.some((x) => codeOf(x) === 'E9999'));
    const changed = waitForDiagnosticsChange(uri);
    await vscode.commands.executeCommand('pythonta.check');
    await changed;
    const codes = pytaDiagnostics(uri).map(codeOf);
    assert.ok(codes.includes('E9999'), `expected E9999 after re-check: ${codes}`);
  });
});
```

- [ ] **Step 3: Run the integration suite**

```bash
ls bundled/libs/python_ta >/dev/null || $PY scripts/bundle.py build
npm run test:integration
```
Expected: VS Code stable downloads into `.vscode-test/` on the first run, `ms-python.python` is installed automatically as an `extensionDependencies` entry, and `4 passing`. If the run cannot find a Python, the extension logs `No Python 3.10 or newer was found`; make sure `python` is on PATH in the shell that launches the test.

- [ ] **Step 4: Commit**

```bash
git rm -q --cached test/integration/.gitkeep 2>/dev/null; rm -f test/integration/.gitkeep
git add .vscode-test.mjs test/integration
git commit -m "test(ext): VS Code integration tests over the fixture workspace"
```

---

### Task 12: CI, release workflow, README, and first push

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Write `ci.yml`**

`.github/workflows/ci.yml`:
```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  python:
    name: python tests (${{ matrix.os }}, py${{ matrix.python }})
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python: ['3.10', '3.13']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e "server[dev]"
      - run: python -m pytest server/tests -q

  node:
    name: extension unit tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - run: npm ci
      - run: npm test

  bundle:
    name: bundle + integration (${{ matrix.os }})
    needs: [python, node]
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - run: npm ci
      - name: Build bundled libs
        run: python scripts/bundle.py build
      - name: Python tests against the bundle only (no python-ta installed)
        if: runner.os == 'Linux'
        run: |
          python -m venv .venv-bare
          .venv-bare/bin/python -m pip install --quiet pytest pytest-asyncio packaging
          .venv-bare/bin/python -m pip install --quiet --no-deps pytest-lsp
          PYTHONPATH="$PWD/bundled/libs" .venv-bare/bin/python -m pytest server/tests -q -p no:cacheprovider
      - name: Integration tests (Linux)
        if: runner.os == 'Linux'
        run: xvfb-run -a npm run test:integration
      - name: Integration tests
        if: runner.os != 'Linux'
        run: npm run test:integration
      - name: Package VSIX
        if: runner.os == 'Linux'
        run: |
          npm run build:prod
          npx @vscode/vsce package --no-dependencies -o pyta-checker.vsix
      - uses: actions/upload-artifact@v4
        if: runner.os == 'Linux'
        with:
          name: pyta-checker-vsix
          path: pyta-checker.vsix
```

- [ ] **Step 2: Write `release.yml`**

`.github/workflows/release.yml`:
```yaml
name: release

on:
  push:
    tags: ['v*']

permissions:
  contents: write
  id-token: write

jobs:
  release:
    runs-on: ubuntu-latest
    env:
      VSCE_PAT: ${{ secrets.VSCE_PAT }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.13'
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
      - name: Check tag matches package.json version
        run: |
          expected="v$(node -p "require('./package.json').version")"
          if [ "$expected" != "${GITHUB_REF_NAME}" ]; then
            echo "tag ${GITHUB_REF_NAME} does not match package.json version ${expected}"; exit 1
          fi
      - run: npm ci
      - run: python scripts/bundle.py build
      - run: npm run build:prod
      - run: npx @vscode/vsce package --no-dependencies -o "pyta-checker-${GITHUB_REF_NAME}.vsix"
      - name: GitHub release
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh release create "${GITHUB_REF_NAME}" pyta-checker-*.vsix --generate-notes
      - name: Publish to Marketplace (trusted publishing)
        if: vars.VSCE_USE_OIDC == 'true'
        run: npx @vscode/vsce publish --oidc --no-dependencies --packagePath pyta-checker-*.vsix --skip-duplicate
      - name: Publish to Marketplace (personal access token)
        if: vars.VSCE_USE_OIDC != 'true' && env.VSCE_PAT != ''
        run: npx @vscode/vsce publish --no-dependencies --packagePath pyta-checker-*.vsix --skip-duplicate
      - name: Marketplace publish skipped
        if: vars.VSCE_USE_OIDC != 'true' && env.VSCE_PAT == ''
        run: echo "No VSCE_PAT secret and VSCE_USE_OIDC is not 'true'; VSIX is attached to the GitHub release only."
```

- [ ] **Step 3: Write the README and changelog**

`README.md`:
```markdown
# PythonTA Checker

See exactly what [PythonTA](https://www.cs.toronto.edu/~david/pyta/) will flag, as squiggles in VS Code, with one click and no `pip install`.

Built for University of Toronto courses (CSC108, CSC110/111, CSC148) that grade with PythonTA. Not affiliated with the University of Toronto or the PythonTA maintainers.

## Why

- **No install step.** PythonTA and everything it needs ship inside the extension. You need Python 3.10 or newer on your machine, which the course already requires, and nothing else.
- **Matches the grader.** Course starter files end with `python_ta.check_all(config={...})`. This extension reads that block and applies the same config, so you do not get false positives like "forbidden import random" that the grader would never report.
- **Only PythonTA, if you want.** Optionally hide Pylance and basedpyright problems so the Problems panel shows one source of truth. Autocomplete keeps working.
- **Never runs your code.** Files are parsed, not executed.

## Install

1. Install [Python 3.10+](https://www.python.org/downloads/) if you have not already.
2. Install **PythonTA Checker** from the VS Code Marketplace. The Python extension is installed with it automatically.
3. Open a `.py` file. Problems appear on open and on save. Click the `PyTA` item in the status bar to re-check.

If nothing appears, open **View > Output** and pick **PythonTA** from the dropdown. The log says which Python was found and what the server did.

## Commands

| Command | What it does |
| --- | --- |
| PythonTA: Check Current File (`Ctrl+Alt+T`, `Cmd+Alt+T` on macOS) | Save and check the active file now. |
| PythonTA: Toggle Only-PythonTA Problems | Hide or show Pylance/basedpyright problems. |
| PythonTA: Restart Server | Restart the language server (for example after installing a different Python). |
| PythonTA: Show Output Log | Open the PythonTA log. |

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `pythonta.runOnSave` | `true` | Check a file each time it is saved. |
| `pythonta.runOnOpen` | `true` | Check a file when it is opened. |
| `pythonta.configPath` | `""` | PythonTA config file used when the file has no embedded `check_all(config=...)`. Relative to the workspace folder. |
| `pythonta.importStrategy` | `useBundled` | `useBundled` runs the PythonTA inside the extension. `fromEnvironment` prefers the PythonTA installed in your selected interpreter and falls back to the bundled one. |
| `pythonta.interpreter` | `""` | Absolute path to a Python executable; overrides the Python extension's selection. |
| `pythonta.hideOtherPythonDiagnostics` | `false` | Managed by the toggle command. When true, `python.analysis.ignore` and `basedpyright.analysis.ignore` are set to `["**"]` in your user settings; turning it off restores the previous values. |
| `pythonta.trace.server` | `off` | Language server tracing. |

## How the config is found

For each file, in order:

1. The `config=` argument of the first `check_all(...)` or `check_errors(...)` call in the file. A dict literal is used directly; a string is a path relative to the file.
2. `pythonta.configPath`, if set.
3. PythonTA's defaults.

Severity: PythonTA "error" messages are red, everything else (warning, refactor, convention) is yellow. Every message links to its documentation; codes not on the PythonTA page link to pylint's docs.

## Other editors

The checker is a standalone language server. With the Python package from `server/` installed (`pip install ./server`), `python -m pyta_lsp` speaks LSP over stdio and can be wired into Zed, Neovim, or Helix. A PyPI release and a Zed extension are planned.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "server[dev]"     # POSIX: .venv/bin/python
.venv/Scripts/python -m pytest server/tests -q
npm ci
npm test                                                 # type-check, lint, unit tests
.venv/Scripts/python scripts/bundle.py build             # builds bundled/libs (needed to run the extension)
npm run test:integration                                 # launches VS Code against test/fixtures
```

Press F5 in VS Code to run the extension against `test/fixtures`.

Update PythonTA: change the pin in `server/requirements.in`, run `python scripts/bundle.py lock` then `build`, run the tests, commit the lockfile and `THIRD_PARTY_NOTICES.md`.

## Releasing

1. Bump `version` in `package.json` and `server/pyproject.toml`, update `CHANGELOG.md`, commit.
2. `git tag vX.Y.Z && git push --tags`. The release workflow builds the VSIX, attaches it to a GitHub release, and publishes to the Marketplace.

Marketplace publishing needs a one-time setup by the repository owner:

- Create a publisher at https://marketplace.visualstudio.com/manage with ID `ThePoNGz` (must equal `publisher` in `package.json`).
- Either configure trusted publishing for this repository's `release.yml` in the publisher settings and set the repository variable `VSCE_USE_OIDC` to `true`, or create an Azure DevOps personal access token (organization: all accessible organizations; scope: Marketplace > Manage) and store it as the repository secret `VSCE_PAT`. Personal access tokens are being retired by the Marketplace at the end of 2026, so trusted publishing is preferred.

Without either, the workflow still attaches the VSIX to the GitHub release, which users can install with `code --install-extension`.

## License

MIT. See `LICENSE`.

The extension bundles unmodified third-party Python packages; see `THIRD_PARTY_NOTICES.md` for the list and their licenses. PythonTA's package metadata declares MIT while its repository LICENSE file is GPL-3.0; this project redistributes the published wheel unchanged. See https://github.com/pyta-uoft/pyta.
```

`CHANGELOG.md`:
```markdown
# Changelog

## 0.1.0 (unreleased)

- Check Python files with PythonTA on open, on save, and on command; results appear as squiggles and in the Problems panel with links to the docs.
- PythonTA and its dependencies are bundled; no pip install required.
- The `check_all(config=...)` block embedded in course files is honored.
- Optional Only-PythonTA mode hides Pylance and basedpyright diagnostics.
- Status bar item showing server and per-file state.
```

- [ ] **Step 4: Run everything once more, commit, push**

```bash
$PY -m pytest server/tests -q
npm test
npm run build:prod
npx @vscode/vsce package --no-dependencies -o pyta-checker-0.1.0.vsix
ls -la pyta-checker-0.1.0.vsix
git add .github README.md CHANGELOG.md
git commit -m "ci: test matrix, release workflow, and documentation"
git push -u origin main
```
Expected: all tests pass, a VSIX of roughly 10 to 15 MB is produced, and the push succeeds. Open https://github.com/ThePoNGz/pyta-checker/actions and confirm the `ci` workflow runs; fix anything red before moving on.

---

### Task 13: Manual verification in a clean profile

**Files:** none new. Notes go into `CHANGELOG.md` only if something changes.

- [ ] **Step 1: Install the VSIX into a fresh profile**

```bash
code --profile pyta-clean --install-extension pyta-checker-0.1.0.vsix
code --profile pyta-clean test/fixtures
```
The `pyta-clean` profile has no other extensions; VS Code installs `ms-python.python` because it is an extension dependency.

- [ ] **Step 2: Check each behavior**

- Open `course_style.py`: squiggles appear within a few seconds; the Problems panel lists PythonTA entries; `E9999` is absent; hovering a squiggle shows `E9989` as a link that opens the PythonTA docs at `#e9989`.
- Status bar shows `PyTA N`; open `clean.py` and it shows a check mark.
- Introduce `total=0` style errors, save: the count updates.
- Run "PythonTA: Toggle Only-PythonTA Problems": Pylance squiggles disappear, PythonTA's stay; toggle again: they return.
- Run "PythonTA: Restart Server": the status bar spins then returns.
- Set `pythonta.interpreter` to a nonsense path: an error notification appears with "Select Interpreter" and "How to install Python"; clear the setting: the server comes back.
- Output panel > PythonTA: the log says which Python it used and shows `PythonTA server started`.

- [ ] **Step 3: Clean up**

```bash
code --profile pyta-clean --uninstall-extension ThePoNGz.pyta-checker
```
Record any bug found as a fix commit before tagging a release. Do not tag `v0.1.0` in this plan; the owner decides when to publish.

---

## Plan self-review notes

- Spec coverage: runner (4.1) Task 4; server (4.2) Task 5; mapping (4.3) Task 3; extension, commands, settings, status bar (4.4) Tasks 7 to 9; only-PythonTA (4.5) Task 10; bundling (4.6) Task 6; other editors (4.7) server packaging in Task 1 and README in Task 12; layout (5) Tasks 1 and 7; testing (6) Tasks 2 to 11; CI and release (7) Task 12; licensing (8) Tasks 1, 6, 12.
- Import strategy is applied by the runner reordering `sys.path` (Task 4) using env vars set by the extension (Task 7); the server process always uses the bundled pygls.
- The spec's "restart the type checkers" uses the verified command ids `python.analysis.restartLanguageServer` and `basedpyright.restartserver` (Task 10).
- The spec's docs-URL rule is implemented with the generated code set plus pylint fallback (Task 3).
