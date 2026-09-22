# PythonTA Checker: devlog

A record of why this project exists, what was found during research, what was decided, how it is built, and how the build went. Written at the end of the initial build (2026-09-21 to 2026-09-22). The design spec and the implementation plan it summarizes live next to it:

- `docs/superpowers/specs/2026-09-22-pyta-checker-design.md` (binding design)
- `docs/superpowers/plans/2026-09-22-pyta-checker.md` (task-by-task plan with code)

## 1. Why

University of Toronto CS courses (CSC108, CSC110/111, CSC148) grade code style with PythonTA (`python-ta` on PyPI), a wrapper around pylint. In 2026 the courses moved from PyCharm to VS Code but shipped no working editor integration. Students are told to `pip install python-ta`; roughly half fail, mostly because the pip they run belongs to a different Python than the one VS Code uses.

The courses invoke PythonTA from a block at the bottom of every starter file:

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

Running the file executes that block and opens an HTML report in the browser. The config dict is what the graders use.

Goals set for this project:

1. One click. Install from the Marketplace, open a file, see what PythonTA will flag. No pip, no PATH, no venv.
2. Match the grader. Honor the embedded `check_all(config=...)`.
3. Only PythonTA, optionally. Hide Pylance and basedpyright diagnostics so a student sees one source of truth. Autocomplete keeps working.
4. Editor-agnostic core. A standalone language server so Zed (the owner's editor) can reuse it later.
5. Never execute the student's file.

## 2. Research findings

### The university's own attempts

There are two repositories under `pyta-uoft`, and the one linked from the course is not the real one:

- `pyta-uoft/pyta-vscode-extension`: a two-commit, 144-line prototype (July 2026). One command, spawns `python -m python_ta --output-format pyta-lsp`, on-demand only. Its `configPath` setting is dead code.
- `pyta-uoft/python-ta-vscode-extension`: actively developed (through August/September 2026), a fork of Microsoft's Python tools extension template, real pygls server, tests, CI. Unpublished, marked preview, requires Python 3.13 for its bundled server.

Neither handles a missing PythonTA install, and both run pyta from the command line on the file, which ignores the embedded config. Measured on a course-style sample: the plain CLI produced three extra false positives (two forbidden-import, one forbidden-IO) that the file's own `check_all` config suppresses. Neither is on the Marketplace.

### PythonTA facts (verified against python-ta 2.13.1)

- `check_all(module_name, config, output, load_default_config, autoformat, on_verify_fail, pylint_args)`. `config` is a dict or a path; `output` is a path or a text stream.
- Reporters are chosen with the config key `output-format`: `pyta-plain`, `pyta-color`, `pyta-html` (default, opens a browser), `pyta-json`, `pyta-lsp`. A dict config with `'output-format': 'pyta-json'` and `output=io.StringIO()` yields JSON and no browser. For a path config the override must be `pylint_args=['--output-format', 'pyta-json']` as two list items; the single-string form is silently ignored.
- JSON schema per message: `msg_id`, `symbol`, `msg`, `category`, `line` (1-based), `column` (0-based), `end_line`, `end_column` (0-based, exclusive, null for pycodestyle messages), `snippet`.
- pyta's own `pyta-lsp` reporter drops the symbol, maps pycodestyle style issues to Error, emits zero-width ranges, and carries no docs link. Not used.
- Config discovery looks only for `config/.pylintrc` beside the file; a bare `.pylintrc` next to the file is ignored. Config must be passed explicitly.
- On a syntax error pyta prints an `[ERROR]` line and emits no JSON. On a forbidden `# pylint:` comment it does the same (a "pre-check" failure).
- pyta calls `logging.basicConfig` itself, which only takes effect on the first call in a process.
- `pyta-plain` crashes on Windows code pages (`UnicodeEncodeError`); subprocesses must force UTF-8.
- Docs anchors on the checkers page are the lowercased message id (`#e9989`) for 183 codes; common pylint codes such as C0114, C0200, R1705 are not on that page and need pylint's per-message docs keyed by symbol.
- Import graph: `check_all` imports the HTML reporter, which imports `aiohttp` at module level, so aiohttp must be present even though it is never used.
- Wheels: every dependency has a pure-Python wheel except aiohttp and markupsafe (both build pure from sdist). mypy 1.19 and newer depend on `librt`, a compiled-only runtime, so the bundle pins `mypy<1.19`.
- Licensing: python-ta's wheel declares MIT while the repository LICENSE file is GPL-3.0. pylint is GPL-2.0-or-later, astroid LGPL-2.1, pygls Apache-2.0. Microsoft's `ms-python.pylint` extension is MIT and bundles pylint, which is the precedent followed here.

### Course usage

CSC110/111's public handouts confirm the per-file `check_all(config={...})` pattern ("do not change" it, "the same options we use when grading"), Python from python.org, `python -m pip install python-ta`, no venv. Default output is the HTML report in the browser.

### VS Code ecosystem (verified 2026-09-22)

- `vscode-languageclient` latest is 10.1.1, an exports-only package: `tsconfig` needs `module`/`moduleResolution: Node16`; `outputChannel` must be a `LogOutputChannel`.
- pygls 2.1.1 renamed most of the v1 API (`text_document_publish_diagnostics`, `window_log_message`, `protocol.notify`); `initializationOptions` must be captured in an `INITIALIZE` handler; `@server.thread()` runs handlers on a pool that also hosts the stdin reader.
- `@vscode/python-extension` 1.0.6 exposes `getActiveEnvironmentPath`, `resolveEnvironment`, `onDidChangeActiveEnvironmentPath`.
- Pylance suppresses all diagnostics for matching paths via `python.analysis.ignore` (globs; `["**"]`), without affecting completion; basedpyright has `basedpyright.analysis.ignore`. Restart command ids: `python.analysis.restartLanguageServer` (contributed by the Python extension) and `basedpyright.restartserver` (all lowercase).
- Marketplace personal access tokens retire on 2026-12-01; `vsce publish --oidc` (trusted publishing) is the replacement.
- `pip install --target` writes console scripts into `<target>/bin` even on Windows and they do not see the target dir; launch with `PYTHONPATH=<dir> python -m pyta_lsp`.

## 3. Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Build our own vs contribute upstream | Own extension | Ships on the owner's timeline; the two gaps (install, embedded config) are the whole point; the school's repo is a template fork with a different structure. |
| Architecture | Language server (pygls) plus a thin VS Code client | Editor-agnostic (Zed later), standard diagnostics plumbing. Chosen over a plain "spawn a script" extension. |
| Own server vs Microsoft template | Own pygls server | A few hundred lines instead of two thousand of template code; no Microsoft copyright to carry; the embedded-config feature fits cleanly. |
| Where PythonTA comes from | Bundled pure-Python libs inside the VSIX, run by the student's interpreter | Removes pip entirely. Python itself is still required (the course requires it anyway). A setting prefers an environment install if present. |
| Running pyta | Subprocess per check inside the server | A pyta crash cannot kill the server; pylint's global caches never go stale. |
| Reporter | pyta-json, mapped by us | Carries end positions and symbols; lets us attach docs links and choose severities. |
| Severity | pyta `error`/`fatal` red, everything else yellow | Everything pyta reports is graded; two colors mirror pyta's own report grouping. |
| Docs link | pyta page anchor when documented, else pylint's page by symbol | Verified anchor scheme; mandatory fallback for common codes. |
| Only-PythonTA mode | Write `["**"]` to the two ignore settings at Global scope, remember previous values, restore on toggle | Only mechanism that hides diagnostics while keeping IntelliSense; prompted once, never silent. |
| Security | `capabilities.untrustedWorkspaces.supported = false`; `pythonta.interpreter` scope `machine` | The extension executes a configured interpreter and reads config files that can run code via pylint `init-hook`; Workspace Trust is the standard gate. |
| Engine floor | `^1.101.0`, with `@types/vscode` pinned to match | `vsce` refuses an engine older than the types; raising the floor to the newest VS Code would lock students out. |
| Licensing | Extension MIT; third-party packages bundled unmodified with their license files plus a generated notices file; the pyta MIT/GPL discrepancy stated plainly | No third-party source is committed. |
| Process | Spec, then a plan with complete code per task, then one fresh implementer subagent per task with a review after each and a whole-branch review at the end | Keeps the controller's context clean; every task gets an independent check. |

## 4. Architecture

```
VS Code extension (TypeScript, vscode-languageclient 10)
   | launches: <python> -m pyta_lsp    with PYTHONPATH=<ext>/bundled/libs (always)
   |           env: PYTHONIOENCODING=utf-8, PYTHONUTF8=1, PYTA_LSP_LIBS, PYTA_LSP_IMPORT_STRATEGY
   v
Language server (Python, pygls 2)      one per VS Code window, stdio
   | on didOpen / didSave / executeCommand("pyta.check", [uri]):
   | spawns: <python> -m pyta_lsp.runner <file> [--config P] [--workspace-root D]
   | at most two checks at a time; a newer request kills and supersedes the old one; 60 s timeout
   v
Runner (Python, one-shot)              cwd = the file's folder
   | 1. ast.parse the file (SyntaxError => synthetic E0001, pyta never called)
   | 2. extract check_all(config=...) or check_errors(config=...): dict literal or path string
   | 3. python_ta.check_all(file, config=..., output=StringIO) with the JSON reporter
   |    stdout/stderr and logging captured into the result's "log"
   ^  JSON: {ok, config_source, messages, log, warnings, error, traceback, pyta_version, pyta_location}
Server maps messages to LSP diagnostics (UTF-16 columns, end-of-line fallback, docs links),
publishes them through a generation guard, and sends "pyta/status" {uri, state, count}
```

Config precedence in the runner: embedded dict or path, then the `pythonta.configPath` setting, then pyta defaults. With import strategy `fromEnvironment` the runner moves the bundled libs to the end of `sys.path` before importing python_ta, so an installed copy wins and the bundle is the fallback.

Extension responsibilities: interpreter discovery (setting, then the Python extension's active environment, then `python`/`python3`/`py` on PATH, each probed and accepted only at 3.10 or newer), server lifecycle with serialized restarts, four commands, a status bar item driven by `pyta/status`, and the only-PythonTA mode.

File map:

| Path | Responsibility |
| --- | --- |
| `server/pyta_lsp/config_extract.py` | AST extraction of the embedded config |
| `server/pyta_lsp/runner.py` | one-shot checker CLI and result contract |
| `server/pyta_lsp/diagnostics.py`, `pyta_codes.py` | JSON message to LSP diagnostic; generated set of documented codes |
| `server/pyta_lsp/scheduler.py` | per-document subprocess scheduling: supersede, kill, timeout, concurrency bound, publish guard |
| `server/pyta_lsp/server.py`, `__main__.py` | pygls server, handlers, settings, logging setup |
| `scripts/bundle.py`, `server/requirements.lock` | universal lock (uv) and pure-wheel bundle build with notices generation |
| `scripts/gen_pyta_codes.py` | regenerates the documented-code set from the pyta docs page |
| `src/pythonVersion.ts`, `pythonSelect.ts`, `python.ts` | interpreter discovery (pure parts unit-tested) |
| `src/serverEnv.ts`, `settings.ts`, `client.ts` | server launch environment, typed settings, LanguageClient |
| `src/statusBar.ts` | status bar states |
| `src/onlyPytaLogic.ts`, `onlyPyta.ts` | only-PythonTA planning (pure) and VS Code glue |
| `src/extension.ts` | activation, commands, restarts |
| `test/fixtures/` | course-style sample files shared by all test layers |
| `test/unit/`, `test/integration/`, `server/tests/` | vitest, @vscode/test-cli, pytest (incl. pytest-lsp) |
| `.github/workflows/ci.yml`, `release.yml` | test matrix and tag-driven release |

## 5. The plan

Thirteen tasks, each with tests written first and the full code in the plan document:

1. Repo scaffold and Python package skeleton
2. Fixtures and embedded-config extraction
3. Documented-code set and diagnostic mapping
4. The runner
5. Scheduler and language server
6. Lockfile and bundle build
7. Extension scaffold, manifest, pure helpers
8. Interpreter discovery, language client, lifecycle
9. Status bar
10. Only-PythonTA mode
11. VS Code integration tests
12. CI, release workflow, README
13. Clean-profile install check

## 6. Execution log

Dates are 2026-09-21 (research, design) and 2026-09-22 (plan and build). Each task was implemented by a fresh subagent from its task brief, reviewed by a separate subagent against the brief and the spec, and fixed in scoped rounds where the review found Important issues. A final whole-branch review closed the build.

| Task | Result | Review findings and fixes |
| --- | --- | --- |
| 1 Scaffold | done | clean |
| 2 Config extraction | done | added a test for a config literal that is neither dict nor string |
| 3 Diagnostics | done | pyta's page now documents W0612, one URL assertion adjusted; fix round: honor partial end positions (end line without end column, and the reverse) |
| 4 Runner | done | fix round 1: pyta's `basicConfig` binds to the first call's buffer, so a per-check logging handler was added, `sys.path` restored, synthetic E0001 got the full key set; fix round 2: the handler needs pyta's `[%(levelname)s]` format or the `[ERROR]` fallback never matches (regression fixture with a forbidden `# pylint:` comment) |
| 5 Server | done | test-side corrections for pytest-lsp (server capabilities from InitializeResult, tuple diagnostics, notification future registered before the request); fix round: pygls logging quieted to WARNING (it logged every JSON-RPC body at INFO), publishes routed through a generation guard so a close during a check cannot leave stale diagnostics, reaping and timeouts tightened |
| 6 Bundle | done | mypy 1.20 needs compiled `librt`, pinned `mypy<1.19`; fix round: strip the interpreter-stamped `include/` tree, correct the notices wording about python-ta's missing license file, broaden Project-URL matching so homepages are filled, `-B` on the verify interpreter |
| 7 Extension scaffold | done | clean |
| 8 Client and lifecycle | done | a background security scan flagged that the configured interpreter is executed; fix round: initial start goes through the restart mutex, watcher registered first, check command handles errors, `untrustedWorkspaces.supported = false`, machine-scoped settings |
| 9 Status bar | done | one-line fix: the starting state's click runs a check, per spec |
| 10 Only-PythonTA | done | fix round: setting writes serialized through a promise chain, activation call guarded, toggle guarded |
| 11 Integration tests | done, 4 passing in a real VS Code | fix round: a vacuous assertion replaced with specific codes; the re-check test now edits the file with save-triggered checks disabled and proves the command produced the new diagnostic |
| 12 CI, release, README | done | fix rounds: engine floor restored to 1.101 by pinning `@types/vscode`; lockfile synced |
| 13 Install check | done in an isolated VS Code instance | visual checks left for the owner |

Final whole-branch review: no Critical findings; four Important ones, all fixed in one wave:

- pygls's thread pool (`max_workers=4`) is shared with its stdin reader, so three concurrent checks starved input; now `max_workers=12` with a two-slot semaphore in the scheduler (the spec's concurrency limit).
- A restart requested during an in-flight start was dropped; now queued.
- "Never runs your code" overclaimed: a pyta config file can execute code via pylint's `init-hook`; docs corrected and the trusted-workspace requirement stated.
- Settings parsing and the failure-diagnostic path had no tests; added.

Plus: `doc.lines` hoisted and guarded, mypy's cache redirected out of the student's folder, prerelease-safe version comparison in the bundle script, the config-change path's promise handled.

Incidents during the build: two subagents died on an API rate limit and were re-dispatched; two launch results carried swapped agent ids, so one fix-round message reached a reviewer (which correctly refused) and a fresh implementer was dispatched; one fix agent was stopped mid-work and a fresh agent finished from the uncommitted edits.

## 7. Verification

| Check | Result |
| --- | --- |
| Server pytest | 66 passed |
| Extension unit (vitest) | 16 passed |
| VS Code integration (@vscode/test-cli) | 4 passing locally and on Windows, macOS, Ubuntu in CI |
| Bare venv against the bundle only (no python-ta installed) | full pytest suite passes |
| VSIX | 7.95 MB, 2845 files, no compiled files, no caches; installs, lists, runs the bundled server from the installed path, uninstalls in an isolated VS Code |
| First CI run (`main` @ 9f8c04e) | 10 of 10 jobs green |

## 8. What remains

For the owner:

- Open the folder in VS Code, trust it, press F5, and look: squiggles on `test/fixtures/course_style.py`, the status bar count, the toggle command hiding Pylance's problems. Nobody has seen the UI yet.
- Create the Marketplace publisher `ThePoNGz`, set up trusted publishing (repo variable `VSCE_USE_OIDC=true`) or a `VSCE_PAT` secret, add an icon, tag `v0.1.0`. Steps are in the README.

Known limits, recorded rather than fixed:

- `Ctrl+Alt+T` is GNOME's terminal shortcut on Linux, so the keybinding is dead there.
- A restart queued during deactivation could start a server that nothing stops (narrow window).
- `scripts/bundle.py` imports `packaging` lazily; the CI bundle job installs nothing beyond pip, so a future lock with duplicate pins would need `pip install packaging` there.
- One post-kill process wait has no timeout.
- The reader-starvation threshold moved from 4 to 12 in-flight checks; mitigated, not eliminated.
- The lockfile has no `--hash` pins.
- Two integration assertions are tautological by construction (the load-bearing ones around them are sound).

Follow-ups from the spec, in rough priority: live checking while typing (debounced `didChange` on a temp copy), a PyPI release of the server and a Zed extension, Open VSX publishing, an optional in-editor HTML report, quick fixes for mechanical messages.

## 9. Working on it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "server[dev]"     # POSIX: .venv/bin/python
.venv/Scripts/python -m pytest server/tests -q
npm ci
npm test                                                 # type-check, lint, unit tests
.venv/Scripts/python scripts/bundle.py build             # builds bundled/libs (needed to run the extension)
npm run test:integration                                 # launches VS Code against test/fixtures
```

Update PythonTA: change the pin in `server/requirements.in`, run `python scripts/bundle.py lock` then `build`, run the tests, commit the lockfile and `THIRD_PARTY_NOTICES.md`.

## 10. Review pass (2026-09-22)

The build was finished but unreviewed by anyone other than the agents that wrote it. This pass ran in three stages: prove it works headlessly, prove it works in a real editor, then have four independent reviewers read it cold, one dimension each.

### Stage 1 and 2: it works

Everything passed. TypeScript type-check, lint, and 16 unit tests; 66 Python tests on **3.14.6**, a version CI does not cover; 4 VS Code integration tests; the bundle verifying in isolated mode (`-I -B`) with python-ta resolving from `bundled/libs` and not the environment.

Three specific claims from this devlog were re-tested rather than trusted:

- **The false positives are real.** Same file, same bundled pyta, embedded config on vs off: `E9999 forbidden-import` twice and `E9998 forbidden-IO-function` once disappear. Exactly the three claimed in section 2.
- **All 183 documented codes have live anchors** on the UofT checkers page. Zero dead links. Both pylint fallback URLs return 200.
- **The Windows encoding hazard is handled.** A file with accented characters and an emoji produced correct diagnostics with no `UnicodeEncodeError`.

Hands-on in a real editor confirmed one squiggle on the indexing line and none on the imports, the `print`, or the two 100-character lines, with correct severity layering where two diagnostics overlap on one line.

### Stage 3: what four reviewers found

Passing tests and working hands-on turned out not to mean safe to ship. Every finding below was independently reproduced before being accepted.

| Finding | Effect on a student | Status |
| --- | --- | --- |
| `sys.path` pollution (code execution) | A `python_ta.py` beside an opened file is imported and run. `runOnOpen` means opening the file is enough. | **fixed** |
| `sys.path` pollution (shadowing) | A file named `queue.py` — core CSC148 material — breaks checking for *every* file in that folder. | **fixed** |
| only-PythonTA snapshots its own sentinel | Settings Sync or uninstall/reinstall makes `["**"]` the value we "restore" to. Pylance silent forever. | **fixed** |
| The toggle was workspace-settable | A cloned repo's `.vscode/settings.json` could rewrite user settings, and toggling off could not escape. | **fixed** |
| Snapshot discarded before the restore write | A failed restore threw away the only record of the original values. | **fixed** |
| `SystemExit` escaped the error handler | A mistyped config path gave zero diagnostics and `runner exited with code 32`, real cause swallowed. | **fixed** |
| Column base mismatch | Squiggles land on the wrong token on any line with non-ASCII to the left. | **fixed** |
| `guard()` ignored its own generation | A slow thread could republish stale diagnostics over fresh ones. | **fixed** |
| Orphaned `mypy` grandchildren | Every superseded check leaks a `mypy` process; the scheduler's limit does not bound them. | open |
| Reader starvation at 12 open files | Already recorded in section 8. Raised the threshold; did not remove the mechanism. | open |
| `didOpen` reads disk, maps onto the dirty buffer | After a window reload with unsaved edits, diagnostics can describe text that is not on screen. | open |
| Stale status bar after restart; no `shutdown`/`exit` handler; shared `/tmp` mypy cache; non-UTF-8 coding cookie rejected; config extraction ignores ownership and reachability | minor | open |

### The fixes, in plain terms

**Import shadowing.** Running `python -m` puts the checked file's own folder at the *front* of the import search path, ahead of the bundled libraries and the standard library. Anything in that folder therefore wins. The folder still needs to be searchable so a student's own helper modules resolve, so it is now appended to the *end* of the path instead of the front, and the entry `-m` adds is removed outright. Stdlib and bundle win; student modules still resolve; nothing beside the file can impersonate `python_ta`.

**Only-PythonTA settings.** Three separate changes. The snapshot no longer records our own `["**"]` as if it were a user value — when it sees the sentinel with no snapshot it records "absent", so disabling removes the setting rather than restoring the sentinel. The setting is now `scope: application`, so a workspace cannot set it. And the snapshot is deleted only after the restore writes actually land, with "that extension isn't installed" now distinguished from a genuine write failure instead of both being logged as benign.

**SystemExit.** pyta and pylint call `sys.exit()` on bad config, and `SystemExit` is not an `Exception`, so it flew past the handler and killed the process before it could print anything. It is now caught, and since pyta logs the real cause immediately before exiting, that logged line is surfaced as the error.

**Column bases.** PythonTA's JSON mixes two conventions in one message list: anything from astroid/pylint reports a UTF-8 *byte* offset, while `E9989` (pycodestyle) and the runner's own `E0001` report *character* offsets. Converting everything would have broken the latter two. The conversion is now per-message, keyed on the code.

**Generation guard.** The guard compared "last completed" against "newest" but never against the generation of the thread actually calling it, so a straggler could publish once a newer run had completed. It now takes its own generation and requires all three to agree.

### Two things worth remembering

- **`bundled/libs/pyta_lsp` is a build artifact, not the source.** The VSIX ships that copy, so a server fix does nothing until `python scripts/bundle.py build` runs. A verification run was briefly fooled by the stale copy before this was noticed.
- **`src/onlyPyta.ts` still has no test coverage.** Only the pure planners in `onlyPytaLogic.ts` are tested. The ordering fix there is verified by reading, not by a test, because exercising it needs a mocked `vscode` module.
