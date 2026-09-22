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
- ~~A restart queued during deactivation could start a server that nothing stops (narrow window).~~ Fixed in section 12.
- `scripts/bundle.py` imports `packaging` lazily; the CI bundle job installs nothing beyond pip, so a future lock with duplicate pins would need `pip install packaging` there.
- One post-kill process wait has no timeout.
- ~~The reader-starvation threshold moved from 4 to 12 in-flight checks; mitigated, not eliminated.~~ Removed in section 12: checks no longer run on the protocol pool.
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
| Orphaned `mypy` grandchildren | Every superseded check leaks a `mypy` process; the scheduler's limit does not bound them. | **fixed** |
| Non-UTF-8 coding cookie rejected | A PEP 263 cookie such as `cp1252` made the file unreadable. | partly; see below |
| Reader starvation at 12 open files | Already recorded in section 8. Raised the threshold; did not remove the mechanism. | open |
| `didOpen` reads disk, maps onto the dirty buffer | After a window reload with unsaved edits, diagnostics can describe text that is not on screen. | open |
| Stale status bar after restart; no `shutdown`/`exit` handler; shared `/tmp` mypy cache; config extraction ignores ownership and reachability | minor | open |

### The fixes, in plain terms

**Import shadowing.** Running `python -m` puts the checked file's own folder at the *front* of the import search path, ahead of the bundled libraries and the standard library. Anything in that folder therefore wins. The folder still needs to be searchable so a student's own helper modules resolve, so it is now appended to the *end* of the path instead of the front, and the entry `-m` adds is removed outright. Stdlib and bundle win; student modules still resolve; nothing beside the file can impersonate `python_ta`.

**Only-PythonTA settings.** Three separate changes. The snapshot no longer records our own `["**"]` as if it were a user value — when it sees the sentinel with no snapshot it records "absent", so disabling removes the setting rather than restoring the sentinel. The setting is now `scope: application`, so a workspace cannot set it. And the snapshot is deleted only after the restore writes actually land, with "that extension isn't installed" now distinguished from a genuine write failure instead of both being logged as benign.

**SystemExit.** pyta and pylint call `sys.exit()` on bad config, and `SystemExit` is not an `Exception`, so it flew past the handler and killed the process before it could print anything. It is now caught, and since pyta logs the real cause immediately before exiting, that logged line is surfaced as the error.

**Column bases.** PythonTA's JSON mixes two conventions in one message list: anything from astroid/pylint reports a UTF-8 *byte* offset, while `E9989` (pycodestyle) and the runner's own `E0001` report *character* offsets. Converting everything would have broken the latter two. The conversion is now per-message, keyed on the code.

**Generation guard.** The guard compared "last completed" against "newest" but never against the generation of the thread actually calling it, so a straggler could publish once a newer run had completed. It now takes its own generation and requires all three to agree.

**Orphaned mypy.** PythonTA runs mypy in a subprocess of its own on every check, with no timeout, and killing the runner left that mypy running — outside `max_parallel`, so save-heavy editing could stack up several at once. The runner is now spawned in its own process group (`CREATE_NEW_PROCESS_GROUP` on Windows, `start_new_session` elsewhere) and killed as a tree (`taskkill /F /T`, or `killpg`). The test proves a real grandchild dies with its parent; the specific mypy case was reproduced by the reviewer but runs too fast to sample reliably on this machine.

**Coding cookies, and an upstream wall.** The runner read every file as UTF-8, so a PEP 263 cookie such as `# -*- coding: cp1252 -*-` made it unreadable. It now uses `tokenize.detect_encoding`, matching what python and pylint do — but PythonTA *itself* then fails on such a file with a `UnicodeDecodeError` from its own reader. Measured directly: python runs the file, `pylint` alone rates it 10.00/10, `python_ta.check_all` raises. So the file now parses correctly (a syntax error in it is reported as `E0001` rather than "could not read file"), but it still cannot be checked. Fixing that properly means transcoding to a temp UTF-8 copy, which is the same machinery as checking the editor's unsaved buffer, so it belongs with that work.

### Two things worth remembering

- **`bundled/libs/pyta_lsp` is a build artifact, not the source.** The VSIX ships that copy, so a server fix does nothing until `python scripts/bundle.py build` runs. A verification run was briefly fooled by the stale copy before this was noticed.
- **`src/onlyPyta.ts` had no test coverage at this point.** Only the pure planners in `onlyPytaLogic.ts` were tested, so the ordering fix there was verified by reading rather than by a test. Section 11 closes this.
## 11. Greptile review (2026-09-22)

After the audit above, the branch was run through Greptile's CLI: `greptile review --branch main --agent`. Worth recording that this reviews the committed diff from the merge base through HEAD — it does not need a pull request, which contradicts the earlier assumption that Greptile was PR-only. That assumption came from the MCP tool, whose `trigger_code_review` does require a `prNumber`; the CLI does not.

It was deliberately given no `--instructions`. Telling it what the branch was supposed to fix would have invited it to grade the fixes against their own description rather than against the code.

It was run as a loop: review, fix, review again, until two consecutive passes returned no comments. That took six passes and produced five findings. All five were real, all were P1, and none overlapped with the nine found by the audit — every one sat in code this branch had just written, including code written to fix an earlier pass.

| Finding | What it means | Status |
| --- | --- | --- |
| `taskkill`'s exit status ignored | The Windows tree-kill reported success even when it had failed, skipping the fallback. | **fixed** |
| A refused restore still dropped the snapshot | Uninstalling basedpyright could make a user's original setting unrecoverable. | **fixed** |
| A retained snapshot went stale (pass 2) | After a half-landed restore, a later toggle wrote an old value over a change the user had made since. | **fixed** |
| A refused *enable* write still claimed the setting (pass 3) | Installing the missing extension and configuring it, then disabling, deleted the new value. | **fixed** |
| Reconciliation could fail after writes landed (pass 4) | Judged already harmless once the sentinel guard was in; the real consequence was fixed instead. | declined, see below |
| An edit made while Only-PythonTA was on was lost (pass 5) | A window reload re-asserted the sentinel over the edit and disabling handed back the older value. | **fixed** |

**The ignored exit status.** `subprocess.run` does not raise on a non-zero exit unless `check=True` is passed, and it was not. The code returned unconditionally after calling `taskkill`, so a failed kill counted as a successful one and the `proc.kill()` fallback never ran — leaving the runner and its mypy descendants alive, which is the exact leak the tree-kill was added to close. It now returns only on exit code 0 and otherwise falls through to `proc.kill()`.

**The refused restore.** The fix in section 10 stopped deleting the snapshot when a restore write failed, but treated "that extension isn't installed" as a benign skip rather than as a failure. It is not benign. The sequence: a student has a real `basedpyright.analysis.ignore` value; they turn Only-PythonTA on, so the snapshot is saved and `["**"]` is written into settings.json; they uninstall basedpyright; they turn Only-PythonTA off. The restore is refused because the setting is no longer registered — but the `["**"]` already written is still sitting in settings.json, because uninstalling an extension does not remove its entries. The snapshot, the only record of the original value, was then deleted. Reinstalling basedpyright would bring `["**"]` back into effect with nothing left to restore from. Every refused write now counts as a failed restore; the reason only decides which log line is written.

**This one forced the test coverage.** The note at the end of section 10 said `src/onlyPyta.ts` could not be tested without a mocked `vscode` module. Fixing a data-loss bug in that file blind was not acceptable, so the mock now exists: `test/unit/vscodeStub.ts` provides `workspace.getConfiguration` with settable values and settable per-key rejections, and `vitest.config.mts` aliases `vscode` to it. The regression test walks the full sequence above and asserts the snapshot survives; a second test asserts the snapshot is still dropped when every write lands, so the fix cannot degrade into never cleaning up. Both were watched failing first.

**Four passes in the same small file.** Passes 2 through 5 all landed on `src/onlyPyta.ts` and `src/onlyPytaLogic.ts`, and each fix moved the bug rather than removing it.

- Pass 2: keeping the whole snapshot when *any* restore failed also kept entries that had already been restored. Those are the user's again, so a later toggle wrote a stale value over a change they had made since.
- Pass 3: the mirror image on the enable side. The snapshot was saved in full before any write was attempted, so a write refused because the extension was not installed still recorded a claim on a setting we never touched. Install that extension, configure it, disable Only-PythonTA, and the claim deleted the new value.
- Pass 5: `planEnable` kept whatever the snapshot already held, so an edit made while the sentinel was in place was overwritten on the next enable — a window reload is enough — and disabling later handed back the value from before the edit.

The bookkeeping got steadily more careful and the bug kept surviving, because it was all reasoning about *the past*: what we wrote, what landed, what we think we own. The fix that actually ended it reasons about the present instead.

**The guard that closed the class.** `planDisable` now reads the value on disk and restores a setting only while it still holds our `["**"]` sentinel. A section holding anything else was either never overwritten by us or has been changed since, so it is left alone whatever the snapshot claims. That single check makes every stale-bookkeeping path harmless at once: a refused write leaves a real value in place, so it is skipped; a user edit leaves a real value in place, so it is skipped; a snapshot that over-claims cannot act on the claim.

The per-setting debt model is still there underneath, and still correct — **a section present in the snapshot is one we have overwritten and still owe back**, a landed restore discharges it, a refused one keeps it, and `planEnable` re-records any real value it finds on disk. But it is now the bookkeeping, not the safety. The safety is the guard.

**What was declined.** Pass 4 reported that if the final `globalState` write rejects, the optimistic snapshot saved before the writes stays behind and can claim a setting whose write failed. That is accurate about the snapshot and wrong about the consequence: with the sentinel guard, a claim on a setting that does not hold `["**"]` is never acted on. The review was reasoning about snapshot contents in isolation. What *was* real in that path is that the rejection propagated and skipped the language-server restarts, leaving stale problems on screen until a reload — so the snapshot write is now logged rather than fatal, which is the part worth fixing.

**This is the argument for the loop over a single pass.** Three of the five findings only existed because of a fix made in response to an earlier one. A single review would have found the first two and left a codebase that was, by the end of the loop, demonstrably still losing user settings in three other ways.

**What it did not find.** Nothing in the byte/character column mapping, the generation guard, the import-shadowing fix, or the coding-cookie change — the four most intricate fixes on the branch. It also did not surface the items left open in sections 8 and 10, which is expected: those are design limits rather than defects in the diff it was shown.

## 12. Whole-codebase review (2026-09-22)

Sections 10 and 11 only ever looked at one branch. The majority of this project was written before any review existed, so the branch was merged and then the *whole* codebase was reviewed the same way.

No pull request and no throwaway branch were needed for that. `greptile review --branch <commit>` takes a commit as well as a branch name, so pointing it at the repo's first commit makes the diff it reviews the entire tracked tree - 73 files, about 14,000 lines.

It returned six findings. All six were real. Three were things sections 8 and 10 had already listed as open, which is the first independent confirmation any of them have had; the other three were new.

| Finding | What it means | Status |
| --- | --- | --- |
| `VSCE_PAT` exposed to the whole release job | The Marketplace credential sat in the environment of `npm ci`, the bundle script and the build. | **fixed** |
| A restart could outlive `deactivate()` | Deactivating during interpreter discovery left a language server running that nothing owned. | **fixed** |
| Multi-root workspaces used the first folder's config | Every relative `configPath` resolved against folder one, whichever folder the file was in. | **fixed** |
| Dirty buffers checked stale content | Listed as open in section 10, never confirmed. Now confirmed and fixed. | **fixed** |
| Non-UTF-8 files could be parsed but not checked | Recorded in section 10 as an upstream wall. It was not one. | **fixed** |
| A burst of opens starved the protocol reader | Section 8's known limit, independently reproduced including the worker arithmetic. | **fixed** |

**The credential.** `VSCE_PAT` was declared at job level, so every step ran with it in the environment, including `npm ci` - which executes dependency lifecycle scripts - and both build scripts. None of them need it. The awkward part is that two steps test whether the token exists in their `if:` conditions, and a step `if:` cannot read the `secrets` context. The job now carries `HAS_VSCE_PAT`, a boolean, and the secret itself is declared on the single step that publishes.

**The deactivation race.** `deactivate()` stopped whichever client was already assigned. A restart waiting on interpreter discovery had not assigned one yet, so it sailed past deactivation and started a server afterwards, which then belonged to nobody until the window closed. Deactivation now marks the extension disposed and waits for any restart in flight, and `startServer` checks that flag after discovery returns.

**Two findings, one cause.** The dirty-buffer bug and the encoding wall were the same mistake: the runner was handed the path on disk. That path can hold different text than the editor shows, and it can hold bytes PythonTA cannot read.

Both go away by checking a UTF-8 copy of the buffer instead. The copy cannot sit beside the original - a stray `.py` in a student's folder would be checked, committed and imported by accident - so it goes in a temp directory and the runner gained `--source-dir` for the folder that actually owns the file. Working directory, the `sys.path` entry and relative config paths all resolve against that, so sibling imports and embedded relative configs keep working while the file being parsed lives elsewhere.

Worth correcting the record: section 10 concluded a cp1252 file "still cannot be checked" because PythonTA's own reader raises on it. That was true of the file, not of the situation - PythonTA never has to see those bytes. There is now a test that opens a cp1252 file and asserts real lint diagnostics come back rather than a read failure.

**The starvation.** Section 8 recorded this as an architectural limit and section 10 left it open as needing `check()` rewritten. It needed much less than that. `did_open` and `did_save` ran the check inline on a pygls worker, and that pool also serves the stdin reader, so twelve opens put two workers in a subprocess and ten on the scheduler's semaphore with nothing left to read the next message. Checks now go to a pool of their own and the handlers return immediately; the semaphore still bounds the subprocesses. What made it tractable was a test that asserts `did_open` returns promptly while the check it triggered is still blocked - the behaviour, not the thread arithmetic.

**On the three already-known items.** They had sat in "what remains" for two sections. Having an outside reviewer reach the same conclusions independently is what moved them, and two of the three turned out to be much smaller jobs than they had been written up as.

### Second round

Running the review again on the fixed tree turned up two more, as the branch loop in section 11 did.

**Unrelated `check_all` calls supplied the config.** `_callee_name` returned the attribute of any call, so a student's own helper - `suite.check_all(config={...})` - was treated as PythonTA's, and because the calls were sorted by position it beat the real block at the bottom of the file. The student would then be linted against settings the grader never applies, which is the one outcome this extension exists to prevent. A call now counts only when it resolves to `python_ta`: an attribute on a name bound by importing it, or a bare name imported from it. The course pattern puts that import inside the `__main__` block, so the whole tree is walked rather than the top level.

**A failed release could not be retried.** `gh release create` fails outright on a tag that already has a release, and it runs before Marketplace publishing. So if publishing failed, rerunning the tag died at the first hurdle and never reached `vsce publish --skip-duplicate`, which exists precisely to be retried. The step is now idempotent. A fourth pass then pointed out that `gh release create` drafts, uploads, then publishes, so a run that dies midway leaves a draft that the retry branch would upload to but never publish - so it now publishes explicitly, which is a no-op on a live release.

### What was declined, and why

A fifth pass held at 4/5 on the config change, arguing that `config_extract` still identifies calls by name without scope analysis: a locally shadowed `python_ta`, or a parameter named `check_all` in a file that also imports it, could still match.

That is mechanically true and it is not being fixed. Getting it right means a symbol-table pass over the AST - assignments, parameters, comprehensions, nested scopes, `global` and `nonlocal` - which is a large amount of new machinery, with its own defects, inside the component whose whole job is to read one config block.

The cheap version is worse than the disease. Refusing any name that is rebound anywhere in the file would mean a student with a local variable called `check_all` silently loses their real config and gets diagnostics that do not match the grader. That is the same failure this change was made to prevent, and it is far likelier than someone shadowing the very name they just imported and calling it with a literal `config=` keyword. The original finding described something a student could hit by accident; the residue describes something they would have to construct on purpose.

Recorded as a known limit rather than carried as a defect.

### Where it ended

Five passes. Eight findings, all real, seven fixed and one declined with the reasoning above. Two consecutive passes returned no comments, which is the same stopping rule the branch loop used.

The pattern held from section 11: new findings kept appearing in the code written to fix earlier ones, twice in a row in the release workflow. The reviewer is most useful on code that has just changed, which is an argument for running it as a loop rather than as a gate.

## 13. Review on a pull request (2026-09-22)

The same reviewer, pointed at the same tree through a pull request instead of the CLI, found three more things. Worth recording the comparison, because it is the closest to controlled this project got:

| | Code | Result |
| --- | --- | --- |
| CLI review, 14:25 | `fix/codebase-review` @ `ac7d371` | 0 comments, 5/5 |
| PR review, 15:23 | `main`, the same content after merge | 3 findings, 3/5 |

Same tool, same base commit, effectively the same code. What differed was the context: the pull request carried a written description of what was unverified, which the CLI run never had. That, or run-to-run variation. No controlled test was done, so this is an observation and not a mechanism.

Findings across the round: staging broke package modules (`from . import helper` resolved to nothing in a temp copy, inventing an import error); a workspace-scoped `analysis.ignore` silently outranked the global write so Only-PythonTA reported success while doing nothing; the bundle was built and exercised only on 3.13 though the server supports 3.10; package modules with unsaved edits had disk results mapped onto the buffer; the explicit check command still blocked a protocol worker; and cleanup ran only on a cooperative shutdown, so an editor that crashed left the server and its mypy children running.

Once `greptile.json` existed, findings began arriving phrased as "violates the repository requirement that…", citing the project's own rules rather than generic advice. That was the single highest-value change to how the tool behaves here.

### A correction, and what it cost

Midway through this round a process-leak bug was reported in this session with more confidence than the evidence carried. A probe drove a real server over stdio, opened four documents and sent `shutdown`/`exit`, and the process did not exit within 90 seconds. That was reported as a confirmed hang.

It was not. The probe opened the server's stdout as a pipe and never read it. The server filled the pipe buffer, blocked writing, and so never processed `exit`. The deadlock was in the harness. Draining the pipe, the same server exits in 9.4 seconds. A pile of stray Python processes cited as corroboration were leftovers from killed test runs.

Two process failures, both the same one:

- The regression test written for it passed whether or not the fix was present. Watching a test fail first is the rule this project has followed throughout, and it was skipped precisely where the bug had already been decided to be real.
- A measurement was reported from a harness that had not been validated.

What survived was smaller and real: on shutdown the server left its check subprocesses running until they finished by themselves, 15.5s from `exit` to the process going away, now 9.4s. And the genuine gap, which the review found and the probe had entirely missed, was that none of that cleanup ran when the editor crashed rather than asking politely.

Neither reviewer would have caught the bad probe: a wrong test and a wrong harness both read as correct. Only running it two ways and comparing numbers exposed it. The lesson is narrow and worth keeping — a test that has never been seen to fail has not been shown to test anything.

## 14. Final pre-release review (2026-09-22)

One more pass over the whole tree before the first Marketplace release, this time with three reviewers in parallel, each given one slice (server, extension client, packaging and release) plus the invariants from `greptile.json` and the accepted limits above so they would not re-raise them. The suites were green going in: 93 Python tests, 37 unit tests.

Nineteen findings survived verification; fourteen were fixed, each with a test watched failing first. The two that mattered most were both in the server, and both produced diagnostics the course's own run would not.

| Finding | What it means | Status |
| --- | --- | --- |
| Messages about the config file were pinned on the student's file | A `disable=` naming an option the bundled pylint 4 does not know produced `W0012` for `cfg.txt`, which the server squiggled on line 1 of `a1.py`. | **fixed** |
| Four more character-based column codes | `C0303`, `W0511`, `W1401`, `W1402` report character offsets, not bytes; on a line with non-ASCII text the squiggle started one character early. `C0303` is the ordinary trailing-whitespace path. | **fixed** |
| mypy columns are 1-based | `E9951`-`E9956` forward mypy's start column unchanged, so every type squiggle began one character to the right. The end column is 1-based inclusive, which equals the 0-based exclusive value everything else uses, so only the start moves. | **fixed** |
| `did_close` and `shutdown` ran on the event loop | Neither was threaded, and both can wait on `taskkill`, so closing a tab mid-check stalled every message. | **fixed**, see below |
| One mypy cache directory for every user | A fixed path under `/tmp` is owned by whoever created it; mypy failed for everyone else and PythonTA ignores mypy's exit code, so type messages silently vanished. Now per-user. | **fixed** |
| `load_default_config` dropped | Only `config=` was read from the student's call; `load_default_config=False` was checked against the merged defaults. Now forwarded. | **fixed** |
| Every window open restarted Pylance | With Only-PythonTA on, activation rewrote both sentinels, restarted both servers and repeated the workspace-override toast. Writes are now skipped for a target already holding the sentinel, restarts happen only when a write landed, the toast at most once per session and never from activation. | **fixed** |
| The toggle reported success before doing anything | It wrote the setting and toasted; the real writes ran later through the configuration listener and failed only into the log. The toggle now awaits the apply and reports the outcome, including a workspace override in either direction. | **fixed** |
| "No" on the first-run prompt did nothing | The setting syncs across machines but the prompted flag does not; on a second machine the prompt reappeared with the feature already on. | **fixed** |
| `stop()` on the 2 s default | Clean shutdown with checks in flight measures ~9.4 s (section 13); every mid-check restart timed out and hard-killed. Now 15 s. | **fixed** |
| Shell environment passed to the server | `PYTHONHOME`, `VIRTUAL_ENV`, `CONDA_PREFIX`, `PYTHONSTARTUP` from whatever shell launched VS Code outranked the selected interpreter. Dropped. | **fixed** |
| `greptile.json` in the VSIX | Internal review rules shipped to every user. | **fixed** |
| Release job ran no tests | A tag push never triggered `ci.yml`; both suites now run in the release job before packaging. | **fixed** |
| No icon, changelog "unreleased", missing `homepage`/`qna` | Marketplace listing hygiene. A placeholder icon is in `media/`. | **fixed** |

**Shutdown could not be threaded, and the reason is worth keeping.** `@server.thread()` on `shutdown` breaks every pytest-lsp teardown with `JsonRpcRequestCancelled`. pygls implements `lsp_shutdown` as a generator that resumes in the worker's done-callback, where the request-id context variable is unset, so its own "cancel every other pending request" loop cancels the request it is answering. The kill now goes to a non-daemon thread of its own; the interpreter joins it on the way out, and `__main__` still calls `stop_checks` synchronously once `start_io` returns, so the crash path from section 13 is unchanged.

**One invariant bent on purpose.** `did_close` is now on the pygls pool, which is the pool the stdin reader shares and which the rule in `greptile.json` says must not wait on a subprocess. It is bounded: a process is registered for a URI only while it holds one of `max_parallel` slots, so at most two of twelve workers can be parked in a kill, and every other close returns at once. The alternative, the server's own executor, is shut down by `stop_checks`, and a close arriving after that would raise. The rule now records the exception. A second, diff-introduced ordering issue was fixed in the same place: `clear` published the empty list *after* the kill wait, so a file closed and reopened mid-check could have its fresh results wiped; it now publishes first.

**Declined or deferred, with reasons.**

- ~~A message about a broken course config went only to the Output log.~~ Fixed in the follow-up: the runner returns those messages separately and the server publishes each as an Information diagnostic on line 1 that names the config file and its line, so a config the course's run would complain about is visible without being mistaken for the student's own problem.
- Student `pylint_args` are still not forwarded. PythonTA reads the first `--output-format` it finds, so a student list containing one would take the JSON reporter away from the runner. Documented in the runner.
- The first-run prompt, if left open while the toggle is used and then answered "No", writes `false` over the newer action. Judged as the user's most recent explicit answer; recorded as a choice.
- PythonTA 2.13.1 itself crashes on `check_all(config={...}, load_default_config=False)` with no `.pylintrc` beside the file; the student's own run crashes identically, so forwarding the flag reproduces the grader. Worth knowing before it is reported as a regression.
- The packaging review confirmed the earlier licence note: python-ta's wheel metadata says MIT, its repository LICENSE is GPL-3.0, and the wheel ships no licence text. `THIRD_PARTY_NOTICES.md` discloses this as it stands; clarifying it is an upstream question.
- A CI step that installs the built VSIX and smoke-tests it, SHA-pinned actions, an integration matrix against the minimum VS Code version, and a test tying `pyta_lsp.__version__` to `package.json` are all sensible and all deferred.

Where it ended: 108 Python tests, 54 unit tests, 4 integration tests, type-check and lint clean, a fresh VSIX built and unpacked to confirm the server in the bundle carried the new code and `greptile.json` did not. A second reviewer over the finished diff walked the seven Only-PythonTA sequences it was given and found no path that loses a user value.

## 15. Second review sweep (2026-09-22)

A second sweep after the release review in section 14. Eleven findings on the server, and two more rounds carried in this branch that the first version of this section left out: one over the build and CI, one over the extension. All reviewed and all but one reproduced before being touched; the exception is noted below. Each was written as a failing test first and watched fail, then fixed, then the whole suite re-run. Going in: 113 Python tests.

| Fix | Where | Test |
| --- | --- | --- |
| The student's folder was `sys.path[0]` during the runner's own imports. `python -m` puts the spawn directory first, and `strip_cwd_from_path()` only runs inside `main()`, so a `string.py`, `json.py` or `dataclasses.py` beside the checked file was imported and executed, killing every check in that folder. mypy, spawned with the same cwd, picked up `random.py` and `datetime.py` the same way on every save. `PYTHONSAFEPATH=1` now covers both routes, and the runner is spawned in the checked file's own directory. | `scheduler.runner_env`, `server.check` | `test_a_sibling_named_after_a_stdlib_module_is_not_imported_at_startup`, `test_a_sibling_random_module_is_not_imported_by_the_mypy_subprocess` (`test_runner.py`); `test_the_runner_is_spawned_in_the_checked_file_s_own_directory`, `test_a_package_module_is_spawned_in_its_own_package_directory`, `test_the_runner_env_keeps_the_spawn_directory_off_sys_path` (`test_server.py`) |
| Every `E9951`-`E9956` was dropped on Windows for every staged file. `run_check` chdir'd to `source_dir` while the file lived in the staging directory, mypy shortens only paths under its cwd, and python_ta's `^(?P<file>[^:]+):` cannot match a drive letter. Now chdir to the checked file's own directory; `source_dir` still drives the `sys.path` append and relative config resolution. | `runner.run_check` | `test_mypy_messages_survive_a_staged_check` (`test_runner.py`) |
| The staged copy never saw the course config. `reset_linter` calls `find_local_config(file_linted)`, which looks for `config/.pylintrc`, `config/pylintrc` or `config/pyproject.toml` *beside the linted file*, so a plain module was checked against a different config than the student's own run — `extra-imports = random` in the course config, `E9999` in the editor, clean on their machine. Staging now copies that file into `<staging>/config/`. | `server.check` | `test_a_staged_check_sees_the_course_config_beside_the_file`, `test_the_local_config_lookup_matches_python_ta_s_own` (`test_server.py`) |
| A non-UTF-8 PEP 263 cookie survived into the UTF-8 copy, so the tokenizer decoded UTF-8 bytes as cp1252 and every non-ASCII character counted twice. A 79-character line became 85 and drew a `C0301` the student's own run never reports, plus a `C2503` about the copy's own encoding. The cookie is now rewritten to `utf-8`; only the encoding name changes, so no line moves. | `server.normalise_coding_cookie` | `test_a_non_utf8_cookie_does_not_survive_into_the_utf8_staged_copy`, `test_a_coding_cookie_is_pointed_at_utf8_without_moving_any_line` (`test_server.py`) |
| A **saved** package module with mixed line endings was refused with "unsaved changes in a package module cannot be checked; save the file first". `matches_disk` compared disk bytes read with `newline=""` against a document the editor had normalised to one EOL. Both sides are normalised now. | `server.matches_disk` | `test_a_saved_package_module_with_mixed_line_endings_is_still_checked`, `test_matches_disk_ignores_the_editor_s_line_ending_normalisation` (`test_server.py`) |
| Exit time scaled with the number of open documents. `cancel_all` bumped the generation only of keys that already held a process, so a thread parked on the slot semaphore woke after shutdown, spawned a fresh runner and waited out its timeout. A `_stopped` flag checked under the lock right after the slot is acquired, and a generation bump for every known key, close it. | `scheduler.cancel_all`, `scheduler.run` | `test_cancel_all_stops_checks_that_are_still_queued_for_a_slot` (`test_scheduler.py`); `test_the_server_exits_while_checks_are_in_flight` tightened to six documents under 5 s (`test_server.py`) |
| The superseded branch called `communicate()` with no timeout, so a tree kill that did not take — `taskkill` exiting nonzero, a grandchild still holding the pipes — parked that pool thread and its slot for good. Both the superseded and the timed-out branch now reap with a 5 second timeout and close `stdout`/`stderr` explicitly. | `scheduler.run` | `test_a_superseded_run_does_not_wait_forever_on_a_failed_kill`, `test_a_timed_out_run_closes_its_pipes_when_the_kill_does_not_take` (`test_scheduler.py`) |
| Anything raising after `notify_status(uri, "checking")` — `mkdtemp`, the staged write, an `OSError` from `Popen` — returned with no diagnostics and no terminal status, so the status bar spun for the rest of the session. The body moved into `_check` with a guard that publishes a failure diagnostic and a `done` status. | `server.check` | `test_a_failure_after_the_checking_status_still_ends_the_check` (`test_server.py`) |
| `lines` came from `doc.lines`, a second read of the document racing a `didChange` between the two, and `str.splitlines` breaks on `\x0c`, `\x0b`, `\x1c`-`\x1e`, `\x85`, `U+2028` and `U+2029`, none of which is a line to the tokenizer or the editor. A form feed in a comment shifted every later message onto the wrong line: `E9989` at column 12 was published at column 0. The source is read once and split on `\r\n`, `\r` and `\n` only. | `diagnostics.split_lines`, `server.check` | `test_split_lines_only_breaks_where_python_and_the_editor_do` (`test_diagnostics.py`), `test_a_form_feed_does_not_shift_every_later_column` (`test_server.py`) |
| `python_ta.check_all('a1.py', {'extra-imports': ['random']})` — a config passed positionally — was ignored with no warning, so the file was checked against stock defaults. `config` falls back to `args[1]` and `load_default_config` to `args[3]`, python_ta's own order. A call carrying `*args` cannot have its slots read at all and now says so instead of guessing. | `config_extract` | Six tests in `test_config_extract.py`, from `test_a_positional_config_dict_is_read` to `test_a_starred_argument_list_is_not_guessed_at` |
| Extraction warnings went only to the Output log, so a student whose config is a module-level variable was checked against stock defaults with no sign in the editor. Each is now also an Information diagnostic on line 1, prefixed `PythonTA config:`. | `server.check`, `diagnostics.config_warning_diagnostic` | `test_a_config_the_extension_could_not_read_is_visible_in_the_editor` (`test_server.py`) |

| `read_pins` shipped one version of a package to every platform when the lock split it by anything other than Python version, so a wheel pinned per platform or per implementation was bundled for all of them. It now refuses such a lock. The purity gate missed `.dll` and versioned `.so.N` names, so a binary could ride into a bundle that claims to be pure Python. CI built the bundle only on 3.10, leaving the newest interpreter untested, and the Linux keybinding was `Ctrl+Alt+T`, which GNOME owns for the terminal. | `scripts/bundle.py`, `.github/workflows/ci.yml`, `package.json` | `test_read_pins_raises_on_non_python_version_split`, `test_strip_bundle_flags_dll_and_versioned_shared_objects` (`test_bundle_script.py`); the matrix runs 3.10, 3.13 and 3.14 and a `bundle-max` job builds the bundle on the newest (commit `2f3a4d8`) |
| A `stop()` that vscode-languageclient refused, because the client was mid auto-restart, was logged and a second client created: the first kept its Python server alive with nothing holding it. `stopClient` waits for the state to settle and retries, `deactivate()` drains whatever is left, and a rejected restart no longer latches `restartPending`. Only-PythonTA judged a workspace or folder override by presence rather than by value and the direction of the toggle, and never inspected folder values per root; a window whose enable cycle wrote nothing overwrote another window's snapshot; the snapshot key was not registered for Settings Sync, so it did not travel with the setting it describes; and an interpreter from `pythonta.interpreter` that failed to probe was replaced silently. | `src/extension.ts`, `src/onlyPyta.ts`, `src/onlyPytaLogic.ts`, `src/python.ts`, `src/pythonSelect.ts` | `waits for the state to settle and retries the stop once`, `does not wait on a client whose server never came up`, `stops a client left behind by a restart when the window closes`, `runs the pending restart once, not twice on the next one`, `lets the saved ignore snapshot travel with the setting it describes` (`extensionLifecycle.test.ts`); `records nothing in a cycle that had nothing to write`, `leaves the user value recoverable when a window that wrote nothing shares the snapshot`, `still treats a sentinel it did not write as absent when the cycle writes something`, `removes a sentinel that no snapshot accounts for at all` (`onlyPyta.test.ts`); `removes a sentinel no snapshot accounts for`, `removes a sentinel the snapshot does not cover and restores the one it does` (`onlyPytaLogic.test.ts`); five overrides tests in `onlyPytaSession.test.ts`; four in `pythonFallback.test.ts`; three in `pythonSelect.test.ts` (commit `ee3c44b`) |
**A residual on 3.10, deliberately.** `PYTHONSAFEPATH` is 3.11+. On 3.10 the only defence left is the directory the runner is spawned in. For a staged check that is a fresh `mkdtemp` holding one subdirectory, `staged/`, and nothing else: the copy and, when there is one, the course config in its own `config/` sit one level below `sys.path[0]`, where no stdlib name can reach them. The first form of this fix put the copy in the spawn directory itself, which is what round 2 below had to take back — a file named `random.py` there was imported at mypy's startup on every save. For a package module, which has to be checked in place, the spawn directory is the package directory, so on 3.10 a `string.py` sitting inside the student's own package can still be imported at runner startup. That one is the residual. `strip_cwd_from_path()` stays as the fallback for everything after `main()` begins. Narrowing it further would mean not checking package modules in place, which section 13 already ruled out for a worse reason.

**The shutdown figure in section 13 was not a constant.** That section records "the same server exits in 9.4 seconds", and section 14 sized the client's 15 s stop budget against it. Both were measuring four open documents. The number grew with the queue — 0.1 s with two, 9.7 s with four, 18.6 s with six, past the budget — because each queued check spawned a runner after shutdown and waited out its own timeout. With the `_stopped` flag it is flat: **0.2 s at two, four and six documents**. The 15 s budget stays, now with room in it rather than none.

**Two things done differently from the review's suggestion.**

- The staged-config lookup is a local copy of `python_ta.config.find_local_config`, not a call to it. Calling the real one would import `python_ta`, and with it pylint and astroid, into a process that lives for the whole session; the whole point of the runner subprocess is that this does not happen. `test_the_local_config_lookup_matches_python_ta_s_own` runs both over the same four layouts, so the copy cannot drift.
- All runner warnings are published as config diagnostics, not a filtered subset. `result["warnings"]` is filled from `extract_config` and nowhere else, so there is nothing to separate.

**The cookie crash could not be reproduced.** The finding was a `setendings` `IndexError` ("string index out of range") on a cp1252 cookie with an accented string. astroid does decode the staged bytes as cp1252 — it reports `end_col_offset` 46 on a line that is 17 characters long — but python_ta 2.13.1 survives it, on 3.14 with this bundle. What is real and was used as the test instead is the wrong column arithmetic that follows from the same mojibake: the spurious `C0301` and `C2503` above. The fix is the one the review asked for either way.

**The `planDisable` contract changed.** Section 10 fixed the same hole from the other end: a sentinel already on disk that no snapshot accounts for is recorded as *absent* at enable time, so the disable that follows removes it rather than restoring our own `["**"]` as if it were the user's. `planDisable` now does that work itself — it covers every section still holding the sentinel, whether the snapshot names it or not, and clears the ones it does not cover. For a single window the net effect is the same. The difference is between windows: recording the absence meant *writing a snapshot*, so a window whose enable cycle changed nothing still overwrote the snapshot another window had left behind, and that window's real user value was no longer recoverable. A cycle that writes nothing now records nothing.

Where it ended: 138 Python tests, green.

### Round 2 (2026-09-22)

The sweep above was then reviewed itself. Nine findings, seven of them in code, and two of those say an earlier fix in this same section landed in the wrong place. Each was again written as a failing test first and watched fail. Going in: 138 Python tests.

| Fix | Where | Test |
| --- | --- | --- |
| The bounded reap added above closed `stdout` and `stderr` from the worker. `close()` waits for Popen's reader thread, and after a tree kill that did not take that thread is still blocked on a grandchild holding the write end, so the close never returned: the worker and its slot were lost for the rest of the session. The two tests passed only because their fake pipes could not block. A process the bounded reap cannot collect is now handed to a daemon reaper that waits for it with no timeout, and `run()` returns at once. | `scheduler._reap_later`, `scheduler.run` | `test_a_timed_out_run_hands_a_process_it_could_not_reap_to_a_reaper`, `test_a_completed_run_leaves_no_pipe_open` (`test_scheduler.py`) |
| The `_stopped` check, the spawn and the registration in `_procs` were three critical sections, so a `cancel_all` landing between them snapshotted a dict that did not yet hold the process about to exist. They are one section now, and the generation is checked in it too, so a run superseded while it waited for a slot never starts a runner at all. | `scheduler.run` | `test_a_spawned_process_is_always_in_the_cancel_all_snapshot`, `test_a_run_superseded_while_it_waits_for_a_slot_never_spawns` (`test_scheduler.py`) |
| The failure guard published a diagnostic and a terminal `done` without the generation guard every other publish goes through, so a check that died in `mkdtemp` or the staged write wiped the diagnostics of a newer check on the same file and flipped its status bar to done while it was still running. `check()` reserves the generation before anything that can fail, `run()` accepts it instead of bumping again, and `fail()` decides under the lock whether the failure is still the newest word on the file. | `scheduler.reserve`, `scheduler.fail`, `server.check` | `test_reserve_claims_the_generation_the_run_then_uses`, `test_reserve_kills_the_process_the_previous_run_left`, `test_fail_completes_only_the_newest_generation` (`test_scheduler.py`); `test_a_failure_from_a_superseded_check_does_not_overwrite_newer_results` (`test_server.py`) |
| With that guard in place, the `os.mkdir`/`shutil.copyfile` that carries the course config into staging could turn a `config/.pylintrc` that is a directory, read-only or on a full disk into a lone "could not check" line, where before the file was at least checked against the defaults. The copy warns and the check goes on. | `server._check` | `test_a_course_config_that_cannot_be_staged_does_not_lose_the_check` (`test_server.py`) |
| `normalise_coding_cookie` split on `"\n"` alone, so a CR-only buffer was a single line and the cookie pattern scanned the whole file: a student's own `encoding=enc` further down was rewritten to `encoding=utf-8`, producing an `E0602` their own run never reports. It splits with `diagnostics.split_lines` now and rejoins on the original separators; a buffer behind a BOM is left as it is. | `server.normalise_coding_cookie` | `test_a_cookie_is_only_looked_for_in_the_first_two_real_lines`, `test_a_buffer_behind_a_bom_is_left_alone` (`test_server.py`) |
| `*args` was taken to make a whole call unreadable, so `check_all(*args, config={...})` was checked against the defaults although its config was right there by keyword: `*args` hides the positions, not the keywords. The other way round, `check_all('a1.py', **CFG)` was silently treated as having no config at all, with no warning. | `config_extract._unpacked`, `config_extract.extract_config` | `test_a_keyword_config_is_read_even_beside_a_starred_argument_list`, `test_a_starred_keyword_dict_is_not_guessed_at` (`test_config_extract.py`) |
| The staged copy was written into the staging directory the runner is then spawned in, which on 3.10 is `sys.path[0]`: a student file named `random.py`, `string.py` or `json.py` was imported and executed during the runner's own imports and again at mypy's startup — the very hole the first row of this section closes for the unstaged case. The copy and its `config/` move to `<staging>/staged/`, and the runner is spawned in `<staging>`, which holds that one directory. `run_check` chdirs only when the file is not already under the cwd, since mypy needs an ancestor and not the file's own folder. | `server._check`, `runner.run_check` | `test_a_staged_file_named_after_a_stdlib_module_is_not_imported`, `test_the_runner_is_spawned_where_no_student_file_can_be_imported` (`test_server.py`); `test_the_runner_stays_in_a_cwd_that_already_holds_the_file`, `test_mypy_messages_survive_a_staged_check` (`test_runner.py`) |

The remaining two findings are this section itself: the missing rows for commits `2f3a4d8` and `ee3c44b` above, and the `planDisable` note.

**Three things done differently from the review's suggestion.**

- The review asked for the blocking close to be fixed on both reaping branches. Making the spawn and the registration atomic removes the post-spawn superseded branch outright — a run superseded while it waited for a slot now returns before spawning anything — so only the timed-out branch still reaps, and only it needed the reaper. `test_a_superseded_run_does_not_wait_forever_on_a_failed_kill` became `test_a_run_superseded_while_it_waits_for_a_slot_never_spawns`, which is the invariant that replaced it. The two changes were committed in that order for the same reason.
- The atomicity test asserts that the process was killed *by the thread that called `cancel_all`*, not merely that it was killed. Killing it was never the gap: the old code's superseded branch killed it from the worker. Being in the snapshot is.
- The refusal to check a package module with unsaved changes publishes through the same new `fail()` guard as the exception path. It is the same shape of publish from the same reserved generation, and leaving it unguarded would have left half the hole open.

`test_the_runner_is_spawned_in_the_checked_file_s_own_directory`, named in the first row of the table above, is now `test_the_runner_is_spawned_where_no_student_file_can_be_imported`: the rule it checks changed with the staging layout.

Where it ended: 151 Python tests and 75 TypeScript tests, green.
