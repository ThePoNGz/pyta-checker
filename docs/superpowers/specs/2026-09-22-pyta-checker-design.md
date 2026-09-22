# PythonTA Checker: design

Date: 2026-09-22
Status: approved by the project owner in conversation; implementation follows the plan in `docs/superpowers/plans/`.

## 1. Problem

University of Toronto CS courses (CSC148 and others) grade code style with PythonTA (`python-ta` on PyPI), a wrapper around pylint with course-specific checkers. The courses moved to VS Code but ship no working editor integration. Students must `pip install python-ta` themselves and roughly half fail, mostly because the pip they run belongs to a different Python than the one VS Code uses.

The courses invoke PythonTA by placing a block at the bottom of every starter file:

```python
if __name__ == '__main__':
    import python_ta
    python_ta.check_all(config={
        'extra-imports': ['random', 'datetime'],
        'allowed-io': ['roll'],
        'max-line-length': 100,
        'disable': ['C0200']
    })
```

Running the file executes that block and opens an HTML report in the browser. The config dict is what the graders use. Running pyta from the command line on the same file ignores the block, so it reports false positives the graders never would (forbidden-import on `random`, forbidden-IO on `print`, and so on). Both of the university's own extension repositories (`pyta-uoft/pyta-vscode-extension`, a two-commit prototype, and `pyta-uoft/python-ta-vscode-extension`, an unpublished fork of Microsoft's Python tools template) run pyta from the command line and therefore have this problem, and neither helps a student who has not installed pyta.

Students who use a strict type checker such as basedpyright also see a wall of diagnostics that have nothing to do with what pyta will flag.

## 2. Goals

1. One click. Install the extension from the Marketplace, open a Python file, see exactly what pyta will flag as squiggles and in the Problems panel. No pip, no PATH, no virtual environment.
2. Match the grader. Honor the `check_all(config=...)` block embedded in the file.
3. Only pyta. Optionally hide Pylance and basedpyright diagnostics so the student sees one source of truth. Autocomplete keeps working.
4. Editor-agnostic core. The checker is a standalone language server so other editors (Zed first) can reuse it later.
5. Never execute student code. The checker parses files; it does not run them.

### Non-goals for this version

- Live checking while typing. Each pyta run costs one to three seconds; on-open, on-save, and on-command are enough for now. The server design must not preclude adding a debounced on-change trigger later.
- Rendering pyta's HTML report inside VS Code.
- Jupyter notebooks.
- Bundling a Python interpreter. The courses already require Python; the extension requires Python 3.10 or newer to be present.
- Publishing the server to PyPI and a Zed extension. The layout supports both; they are follow-ups.

## 3. Facts the design relies on

Verified against python-ta 2.13.1 on 2026-09-21.

- `python_ta.check_all(module_name='', config='', output=None, load_default_config=True, autoformat=False, on_verify_fail='log', pylint_args=None)`. `config` accepts a dict or a path. `output` accepts a path or a text stream. `check_errors` has the same signature and runs only error-category checks.
- The reporter is chosen with the config key `output-format`. Values: `pyta-plain`, `pyta-color`, `pyta-html` (default; opens a browser), `pyta-json`, `pyta-lsp`. Passing a dict with `'output-format': 'pyta-json'` and `output=io.StringIO()` yields JSON with no browser and no other stdout noise.
- JSON schema per file: `{"filename", "msgs": [{"msg_id", "symbol", "msg", "C", "category", "line", "column", "end_line", "end_column", "snippet", "number_of_occurrences", ...}]}`. Lines are 1-based. `end_line`/`end_column` are null for pycodestyle (`pep8-errors`) messages. Categories: `error`, `warning`, `refactor`, `convention`.
- Pyta's own `pyta-lsp` reporter is not used: it drops the symbol, maps pycodestyle style issues to Error severity, and emits zero-width ranges.
- Config discovery in pyta only looks for `config/.pylintrc` (or `config/pylintrc`, `config/pyproject.toml`) beside the file; a bare `.pylintrc` next to the file is ignored. The runner therefore passes config explicitly.
- Import graph: `import python_ta` pulls in requests, typeguard, wrapt, platformdirs. `check_all` additionally imports the reporters package, which imports `html_reporter`, which imports `aiohttp` at module level. So aiohttp must be present even though the HTML reporter is never used. mypy and black are declared dependencies but are not imported by the JSON check path.
- Dependency wheels: every dependency has a pure-Python wheel (`py3-none-any`) except aiohttp and markupsafe. mypy 1.19 and newer additionally depend on `librt`, a compiled-only runtime with no pure build, so the bundle pins `mypy<1.19` (1.18.x ships a pure wheel and is inside python-ta's declared `mypy~=1.13` range); pyta only shells out to mypy for its optional static type checks. aiohttp supports a pure build via `AIOHTTP_NO_EXTENSIONS=1`; markupsafe's C speedup is optional and the package falls back to pure Python when the compiled module is absent.
- Minimum Python: 3.10 for python-ta, pylint 4, astroid 4, aiohttp, mypy.
- Unpacked size of pyta plus dependencies is roughly 28 MB, with mypy about 9 MB of that. Microsoft's pylint extension bundles a comparable amount.
- Licenses: the extension's own code is MIT. python-ta's wheel metadata declares MIT while its repository LICENSE file is GPL-3.0; the maintainers have not clarified. pylint is GPL-2.0-or-later, astroid LGPL-2.1, pygls Apache-2.0. Microsoft's `ms-python.pylint` extension is MIT and bundles pylint, which is the precedent this project follows: bundle unmodified third-party packages with their license files intact and a generated notices file.
- Pylance suppresses all of its diagnostics for matching paths via `python.analysis.ignore` (array of globs; `["**"]` matches everything). The setting affects diagnostics only, not import resolution, completion, or hover. basedpyright has the equivalent `basedpyright.analysis.ignore` and does not read `python.analysis.*`. Neither is documented to apply live without a language-server restart, so the extension restarts them after changing the setting.
- The Microsoft Python extension exposes `@vscode/python-extension` (1.0.6): `PythonExtension.api()`, `environments.getActiveEnvironmentPath()`, `environments.resolveEnvironment()` returning `executable.uri` and `version.major/minor`, and `environments.onDidChangeActiveEnvironmentPath`.

## 4. Architecture

Three layers in one repository. Data flows downward on a check and upward as diagnostics.

```
VS Code extension (TypeScript, vscode-languageclient)
   | launches: <python> -m pyta_lsp   with PYTHONPATH=<ext>/bundled/libs
   v
Language server (Python, pygls)          persistent, one per VS Code window
   | on didOpen / didSave / executeCommand("pyta.check"):
   | spawns: <python> -m pyta_lsp.runner <file> [--config <path>] [--errors-only]
   v
Runner (Python, one-shot)                cwd = folder of <file>
   | 1. ast-parse file, extract check_all(config=...)
   | 2. python_ta.check_all(file, config=merged, output=StringIO)
   | 3. print JSON result
   ^
Server converts JSON to LSP diagnostics, publishes to client
```

### 4.1 Runner (`pyta_lsp/runner.py` and `pyta_lsp/config_extract.py`)

Purpose: check one file and return a machine-readable result. Usable by hand from a terminal for debugging.

Invocation: `python -m pyta_lsp.runner <path> [--config <path>] [--errors-only] [--no-embedded-config]`. Output on stdout is one JSON document:

```json
{
  "ok": true,
  "config_source": "embedded" | "file" | "default",
  "messages": [ ...pyta JSON messages for this file, unchanged... ],
  "log": "<everything pyta printed to stdout/stderr during the check>",
  "warnings": [ "<non-fatal notes, e.g. config argument was not a literal>" ],
  "error": null
}
```

On failure: `{"ok": false, "config_source": ..., "messages": [], "log": "...", "warnings": [...], "error": "<one-line reason>", "traceback": "<full text>"}`. Exit code is 0 in both cases; a non-zero exit means the runner itself could not start (for example, pyta not importable) and stderr carries the reason.

Config extraction rules, applied to the file's syntax tree without executing it:

1. Find the first call whose callee is `check_all` or `check_errors` (as a bare name or attribute, so `python_ta.check_all(...)`, `pyta.check_all(...)`, and `check_all(...)` all match) that has a `config` keyword argument.
2. If the value is a literal (dict, string), evaluate it with `ast.literal_eval`. A dict is the config. A string is a path, resolved relative to the file's folder.
3. If the value is not a literal, or evaluation fails, treat it as absent and record a warning in the result.
4. If the callee was `check_errors`, the runner uses `python_ta.check_errors` instead of `check_all`.
5. Precedence: embedded config, then `--config` from the command line (which the server derives from the `pythonta.configPath` setting), then pyta defaults. When an embedded dict is used, `load_default_config` stays true, matching how the course runs it.
6. The runner always forces the JSON reporter. For a dict config it sets `'output-format': 'pyta-json'` on the dict. For a path config it passes the path through and adds `pylint_args=['--output-format', 'pyta-json']`, two separate arguments, which is what pyta's own CLI does. The single-string form `--output-format=pyta-json` is silently ignored by pyta and must not be used.
7. Pyta prints progress lines such as `Using config file ...` to stdout during a check and writes the report to the `output` stream. The runner redirects stdout and stderr into a buffer for the duration of the check and returns that text in the result's `log` field, so the runner's own stdout carries only the result JSON.
8. Pyta emits no JSON at all for a file with a syntax error; it prints an error line instead. The runner parses the file with `ast.parse` before calling pyta (it needs the tree for config extraction anyway). On `SyntaxError` it skips pyta and returns one synthetic message: `msg_id` `E0001`, `symbol` `syntax-error`, `category` `error`, `line` and `column` from the exception (column converted to 0-based), `msg` from the exception text. A missing file returns `ok: false`.

Execution environment:

- Working directory is the file's folder and it is first on `sys.path`, so sibling modules resolve the way they do when the course runs the file.
- Environment forces UTF-8 (`PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`) because pyta emits non-ASCII characters and crashes on Windows code pages otherwise.
- When the extension uses the bundled libraries, `PYTHONPATH` points at `bundled/libs` and the runner inserts that directory at the front of `sys.path`. When the import strategy is "from environment", `PYTHONPATH` is not set and the interpreter's own python-ta is used; if it is missing, the runner exits non-zero with a clear message and the server reports it.
- The runner never imports or executes the checked file. Pyta itself performs static analysis only.

### 4.2 Language server (`pyta_lsp/server.py`)

Built on pygls 2. Started with `python -m pyta_lsp` (stdio transport).

Handlers:

- `textDocument/didOpen` and `textDocument/didSave`: schedule a check for that document if the corresponding setting (`runOnOpen`, `runOnSave`) is true.
- `textDocument/didClose`: clear that document's diagnostics.
- `workspace/executeCommand` with command `pyta.check` and argument `[uri]`: check now regardless of settings.
- `workspace/didChangeConfiguration`: refresh settings. Settings arrive as `initializationOptions` at startup and through this notification afterward; the schema is the `pythonta` section of the VS Code configuration.

Scheduling: one check per document at a time. A new request for a document that is already being checked cancels the in-flight subprocess and starts a fresh one. Checks for different documents run concurrently up to a small limit (two) so a slow file does not block others. Each run has a 60 second timeout; on timeout the server kills the subprocess and reports it as a failure diagnostic.

Untitled documents (no file path) are ignored. Only documents with language id `python` are checked.

Failure reporting: when the runner returns `ok: false` or crashes, the server publishes a single diagnostic at line 0, severity Error, source `PythonTA`, code `pyta-error`, message `PythonTA could not check this file: <reason>`. The full traceback goes to the client log via `window/logMessage`.

The server must run in-process nothing that can be broken by a bad student file: all pyta work happens in the runner subprocess.

### 4.3 Diagnostic mapping (`pyta_lsp/diagnostics.py`)

Pure function from a pyta JSON message to an LSP diagnostic. Tested in isolation.

| pyta field | LSP field |
| --- | --- |
| `line`, `column` | `range.start` (line minus one; column as given: pyta columns are 0-based, verified against pylint and pycodestyle messages) |
| `end_line`, `end_column` when present | `range.end` (end line minus one, end column as given; pyta end columns are exclusive) |
| `end_line` null | `range.end` = end of the start line (the server passes line lengths from the document text; when unknown, a large column that the client clamps) |
| `category` = `error` | severity Error |
| any other category | severity Warning |
| `msg_id` | `code` |
| docs page for the code | `codeDescription.href`: the pyta checkers page with anchor `#<msg_id lowercased>` when the code is documented there (a generated set of documented codes ships in the server), otherwise pylint's per-message page keyed by the lowercased symbol, otherwise the pyta page with no anchor |
| `symbol` + `msg` | `message` = `"<symbol>: <msg>"` |
| constant | `source` = `"PythonTA"` |

Everything pyta reports is something the grader counts, so nothing is downgraded to Information or Hint. Red versus yellow mirrors pyta's own report, which separates "code errors" from "style and convention".

### 4.4 VS Code extension (`src/`)

Activation: `onLanguage:python`. Declares `extensionDependencies: ["ms-python.python"]` so the Python extension is installed automatically and interpreter discovery works.

Interpreter selection, in order:

1. `pythonta.interpreter` setting if set (absolute path).
2. The Microsoft Python extension's active environment, resolved to check `version.major.minor >= 3.10`.
3. `python3` then `python` then `py -3` on PATH, probed with `-c "import sys; print(sys.version_info[:2])"`.

If none qualifies, the extension does not start the server and shows an error notification with buttons "Select Interpreter" (runs `python.setInterpreter`) and "How to install Python" (opens the course-neutral python.org download page). The status bar shows the error state. The extension listens to `onDidChangeActiveEnvironmentPath` and restarts the server when the interpreter changes.

Server launch: `LanguageClient` with an `Executable` server option: command is the chosen interpreter, args `["-m", "pyta_lsp"]`, `cwd` is the extension directory, env adds `PYTHONPATH=<ext>/bundled/libs` (when `importStrategy` is `useBundled`), `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`. Document selector: `{ scheme: "file", language: "python" }`. The `pythonta` configuration section is passed as `initializationOptions` and synchronized on change. Output goes to a `LogOutputChannel` named "PythonTA".

Commands:

| Command id | Title | Behavior |
| --- | --- | --- |
| `pythonta.check` | PythonTA: Check Current File | Sends `pyta.check` for the active editor's document. Keybinding `ctrl+alt+t` (`cmd+alt+t` on macOS) when `editorLangId == python`. |
| `pythonta.restart` | PythonTA: Restart Server | Re-resolves the interpreter and restarts the client. |
| `pythonta.toggleOnlyPyta` | PythonTA: Toggle Only-PythonTA Problems | Flips `pythonta.hideOtherPythonDiagnostics` and applies it (section 4.5). |
| `pythonta.showOutput` | PythonTA: Show Output Log | Reveals the output channel. |

Settings (`contributes.configuration`, all under `pythonta`):

| Setting | Type | Default | Meaning |
| --- | --- | --- | --- |
| `runOnSave` | boolean | true | Check a file when it is saved. |
| `runOnOpen` | boolean | true | Check a file when it is opened. |
| `configPath` | string | "" | Path to a pyta config file used when the file has no embedded config. Relative paths resolve against the workspace folder. |
| `importStrategy` | `useBundled` or `fromEnvironment` | `useBundled` | Use the pyta shipped inside the extension, or the one installed in the selected interpreter. |
| `interpreter` | string | "" | Absolute path to a Python executable; overrides discovery. |
| `hideOtherPythonDiagnostics` | boolean | false | Managed by the toggle command; see 4.5. Editing it directly has the same effect. |
| `trace.server` | `off`, `messages`, `verbose` | `off` | Standard language client tracing. |

Status bar item, right side: text `PyTA` with a state icon. States: starting, idle, checking, clean (for the active file), N problems (for the active file), error. Tooltip explains the state. Clicking runs `pythonta.check`; in the error state it runs `pythonta.showOutput`.

### 4.5 Only-PythonTA mode

On first activation (tracked in `globalState`), the extension asks once: "Hide Pylance and basedpyright problems so only PythonTA's show? Autocomplete keeps working." Buttons: "Yes", "No". "Yes" sets `pythonta.hideOtherPythonDiagnostics` to true at Global scope. The prompt is never shown again either way.

Applying the setting (on activation and whenever it changes):

- When true: read the current global values of `python.analysis.ignore` and `basedpyright.analysis.ignore` with `inspect().globalValue`, store them in `globalState` under `pythonta.savedIgnore` unless a saved value already exists, then write `["**"]` to both at Global scope. Then run the restart command of each language server that is installed and active (`python.analysis.restartLanguageServer`, contributed by the Python extension, restarts Pylance; `basedpyright.restartserver`, all lowercase, restarts basedpyright; both ids verified against the shipped extension manifests) so the change applies without a window reload.
- When false: restore the saved values (or remove the keys if none were saved), clear `pythonta.savedIgnore`, restart the same servers.
- The extension writes only these two keys and only at Global scope. It never touches workspace settings.

Pyta reports syntax errors itself (`E0001`), so hiding the type checkers' diagnostics loses nothing a student is graded on.

### 4.6 Bundling (`scripts/bundle.py`, `bundled/libs/`)

`bundled/libs/` is not committed. `scripts/bundle.py` produces it deterministically from `server/requirements.lock`:

1. Install the lockfile into `bundled/libs` with `pip install --target bundled/libs --no-deps --only-binary :all: --implementation py --python-version 3.10 -r server/requirements.lock`, which admits only pure-Python wheels.
2. aiohttp and markupsafe are excluded from step 1 and installed from sdist with `--no-binary :all:` and `AIOHTTP_NO_EXTENSIONS=1`, into the same target.
3. Install the server package itself (`server/`) into the target with `--no-deps`.
4. Delete every `*.so`, `*.pyd`, `*.dylib`, `__pycache__`, and `*.dist-info/RECORD` entry that references them, then fail the build if any compiled file remains anywhere under `bundled/libs`.
5. Generate `THIRD_PARTY_NOTICES.md` at the repository root from the `*.dist-info` metadata (package, version, license, homepage) and copy each package's license file next to it if pip did not already.

The lockfile is produced by `uv pip compile --universal --python-version 3.10` inside a throwaway virtual environment created by the same script (`scripts/bundle.py lock`), pinned to python-ta 2.13.1, pygls 2.x and `mypy<1.19`, and committed. The build step strips environment markers and installs every pinned package unconditionally, so dependencies that only newer or older Pythons need (for example `tomli` on 3.10) are always present; unused ones are harmless. Updating pyta is a one-line change plus re-lock.

The VSIX includes `bundled/libs`, `dist/extension.js`, `package.json`, `README.md`, `CHANGELOG.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`. `.vscodeignore` excludes everything else.

### 4.7 Other editors

The server is a normal Python package at `server/` with `pyproject.toml`, module `pyta_lsp`, and console script `pyta-lsp`. Installed with pip it runs as `pyta-lsp` or `python -m pyta_lsp` over stdio, which is all Zed, Neovim, or Helix need. Publishing it to PyPI and writing the Zed extension manifest are follow-ups; nothing in the VS Code layer is required for them.

## 5. Repository layout

```
pyta-checker/
  package.json               extension manifest, scripts, devDependencies
  tsconfig.json, esbuild.mjs, eslint.config.mjs, .vscodeignore, .vscode-test.mjs
  src/
    extension.ts             activate/deactivate, wiring
    client.ts                LanguageClient construction, start/stop/restart
    python.ts                interpreter discovery and version check
    onlyPyta.ts              only-PythonTA mode (settings save/restore, restarts)
    statusBar.ts             status bar item and states
    settings.ts              typed access to the pythonta section
  test/
    unit/                    TypeScript unit tests (vitest): python.ts probing logic, settings, onlyPyta state machine with a fake configuration
    integration/             @vscode/test-cli suite: opens fixtures in a real VS Code, asserts diagnostics
    fixtures/                shared sample Python files (also used by Python tests)
  server/
    pyproject.toml           package metadata, console script, pytest config
    requirements.in          top-level pins (python-ta==2.13.1, pygls>=2,<3)
    requirements.lock        full pin set generated by pip-tools
    pyta_lsp/
      __init__.py, __main__.py
      server.py              pygls server, handlers, scheduling
      runner.py              one-shot checker CLI
      config_extract.py      AST extraction of check_all(config=...)
      diagnostics.py         JSON message to LSP Diagnostic
    tests/
      test_config_extract.py, test_runner.py, test_diagnostics.py, test_server.py
  scripts/
    bundle.py                builds bundled/libs and THIRD_PARTY_NOTICES.md; --lock regenerates the lockfile
  bundled/libs/              build output, gitignored
  .github/workflows/
    ci.yml                   tests, bundle, purity check, VSIX artifact
    release.yml              on tag v*: build, GitHub release, Marketplace publish
  docs/superpowers/specs/    this document
  docs/superpowers/plans/    implementation plan
  LICENSE                    MIT, copyright the project owner
  THIRD_PARTY_NOTICES.md     generated
  README.md, CHANGELOG.md, .gitignore, .editorconfig
```

## 6. Testing

Test-first at every layer.

Python (`pytest`, run against the developer's interpreter with python-ta installed, and in CI against the bundled libs):

- `config_extract`: fixtures with a dict config, a string config, no config, `check_errors`, a non-literal config, an attribute callee, a syntax error in the file (extraction returns "absent" and the runner still reports pyta's E0001).
- `runner`: end-to-end on the fixtures; asserts `ok`, `config_source`, and that the course-style fixture yields no forbidden-import or forbidden-IO messages while the same file without its config does. Timeout and missing-pyta paths are simulated with a stub module on `PYTHONPATH`.
- `diagnostics`: table-driven mapping tests including null end positions, each category, and the code URL.
- `server`: pygls server driven by an in-process client (pytest-lsp) with the runner replaced by a fake subprocess; asserts publish on open, clear on close, cancellation on a second request, and the failure diagnostic.

TypeScript:

- Unit (vitest): interpreter ordering and version parsing, settings defaults, only-PythonTA save/restore logic against an in-memory fake of `WorkspaceConfiguration` and `Memento`.
- Integration (`@vscode/test-cli`): launches VS Code with the built extension and `bundled/libs`, opens `test/fixtures/course_style.py`, waits for diagnostics with source `PythonTA`, asserts the expected codes and the absence of `E9999`. A second test opens `syntax_error.py` and expects `E0001`. Runs in CI on Windows, macOS, and Linux.

Manual verification before release: install the VSIX in a clean VS Code profile with only the Python extension, on a machine with Python but no python-ta, open a course file, confirm squiggles.

## 7. CI and release

`ci.yml` on push and pull request:

1. Python job, matrix of `windows-latest`, `macos-latest`, `ubuntu-latest` by Python 3.10 and 3.13: install `server/` with dev extras, run pytest.
2. Node job on `ubuntu-latest`: `npm ci`, lint, type-check, vitest.
3. Bundle job on `ubuntu-latest`: run `scripts/bundle.py`, assert no compiled files, run the Python tests once more with `PYTHONPATH=bundled/libs` and pyta uninstalled from the interpreter, build the VSIX with `vsce package --no-dependencies`, upload it as an artifact.
4. Integration job, same three operating systems: download the VSIX artifact's inputs (or rebuild), run `vscode-test`.

`release.yml` on tags matching `v*`: same build, then `gh release create` with the VSIX attached and `vsce publish` using the `VSCE_PAT` repository secret. The project owner creates the Marketplace publisher once; the README's "Releasing" section lists the exact steps and the PAT scope. Open VSX publishing is a later addition using `ovsx` with a second secret.

Versioning: semantic, starting at 0.1.0. `CHANGELOG.md` is updated per release.

## 8. Licensing

- `LICENSE`: MIT, copyright 2026 the project owner.
- No third-party source is committed. `bundled/libs` is built from unmodified PyPI packages with their `dist-info` license files intact, and `THIRD_PARTY_NOTICES.md` lists every package with its declared license.
- The README states that pyta's repository LICENSE (GPL-3.0) and its wheel metadata (MIT) disagree, that this project redistributes the wheel as published under its declared license, and links the upstream repository. Asking the maintainers to reconcile the two is recommended but not required for this project.
- No code is taken from either university extension or from Microsoft's template.

## 9. Follow-ups, in rough priority

1. Live checking on change: debounce `didChange`, write the buffer to a temporary file inside the document's folder (so sibling imports still resolve), run the runner on it, rewrite the URI in results.
2. PyPI release of `python-ta-lsp` and a Zed extension manifest.
3. Open VSX publishing.
4. Optional "Show PythonTA report" command rendering pyta's HTML report in a webview.
5. Quick fixes for mechanical messages (trailing whitespace, missing docstring stubs) via LSP code actions.
