# PythonTA Checker

See exactly what [PythonTA](https://www.cs.toronto.edu/~david/pyta/) will flag, as squiggles in VS Code, with one click and no `pip install`.

Built for University of Toronto courses (CSC108, CSC110/111, CSC148) that grade with PythonTA. Not affiliated with the University of Toronto or the PythonTA maintainers.

## Why

- **No install step.** PythonTA and everything it needs ship inside the extension. You need Python 3.10 or newer on your machine, which the course already requires, and nothing else.
- **Matches the grader.** Course starter files end with `python_ta.check_all(config={...})`. This extension reads that block and applies the same config, so you do not get false positives like "forbidden import random" that the grader would never report.
- **Only PythonTA, if you want.** Optionally hide Pylance and basedpyright problems so the Problems panel shows one source of truth. Autocomplete keeps working.
- **Never runs your file.** Files are parsed, not executed. A PythonTA config file can run code through pylint's `init-hook`, which is one reason the extension only activates in a trusted workspace.

## Install

1. Install [Python 3.10+](https://www.python.org/downloads/) if you have not already.
2. Install **PythonTA Checker** from the VS Code Marketplace. The Python extension is installed with it automatically.
3. Open a `.py` file. Problems appear on open and on save. Click the `PyTA` item in the status bar to re-check.

The extension only activates in a trusted workspace (VS Code asks you to trust a folder the first time you open it).

If nothing appears, open **View > Output** and pick **PythonTA** from the dropdown. The log says which Python was found and what the server did. If the file's config (embedded or `pythonta.configPath`) has a problem PythonTA complains about, that shows as an information message on line 1 naming the config file, so a broken config never fails silently.

## Commands

| Command | What it does |
| --- | --- |
| PythonTA: Check Current File (`Ctrl+Alt+T` on Windows, `Cmd+Alt+T` on macOS, `Ctrl+Alt+Shift+T` on Linux) | Save and check the active file now. |
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
| `pythonta.hideOtherPythonDiagnostics` | `false` | Managed by the toggle command. When true, `python.analysis.ignore` and `basedpyright.analysis.ignore` are set to `["**"]` in your user settings; turning it off restores the previous values. VS Code has no uninstall hook, so if you uninstall the extension while this is on, those settings keep the `["**"]` value; turn the toggle off first, or remove the two `analysis.ignore` entries from `settings.json` by hand. |
| `pythonta.trace.server` | `off` | Language server tracing. |

## How the config is found

For each file, in order:

1. The `config=` keyword argument of the first `check_all(...)` or `check_errors(...)` call in the file. A dict literal is used directly; a string is a path relative to the file.
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

`npm run test:integration` requires `bundled/libs` to exist first; a `pretest:integration` guard checks for it and fails fast with the build command above if it is missing.

Press F5 in VS Code to run the extension against `test/fixtures`.

Update PythonTA: change the pin in `server/requirements.in`, run `python scripts/bundle.py lock` then `build`, run the tests, commit the lockfile and `THIRD_PARTY_NOTICES.md`.

## Releasing

1. Bump `version` in `package.json`, `server/pyproject.toml`, and `server/pyta_lsp/__init__.py`, update `CHANGELOG.md`, commit.
2. `git tag vX.Y.Z && git push --tags`. The release workflow builds the VSIX, attaches it to a GitHub release, and publishes to the Marketplace.

Marketplace publishing needs a one-time setup by the repository owner:

- Create a publisher at https://marketplace.visualstudio.com/manage with ID `ThePoNGz` (must equal `publisher` in `package.json`).
- Either configure trusted publishing for this repository's `release.yml` in the publisher settings and set the repository variable `VSCE_USE_OIDC` to `true`, or create an Azure DevOps personal access token (organization: all accessible organizations; scope: Marketplace > Manage) and store it as the repository secret `VSCE_PAT`. Personal access tokens are being retired by the Marketplace at the end of 2026, so trusted publishing is preferred.

Without either, the workflow still attaches the VSIX to the GitHub release, which users can install with `code --install-extension`.

## License

MIT. See `LICENSE`.

The extension bundles unmodified third-party Python packages; see `THIRD_PARTY_NOTICES.md` for the list and their licenses. PythonTA's package metadata declares MIT while its repository LICENSE file is GPL-3.0; this project redistributes the published wheel unchanged. See https://github.com/pyta-uoft/pyta.
