# PythonTA Checker

See exactly what [PythonTA](https://www.cs.toronto.edu/~david/pyta/) will flag, as squiggles in VS Code. One click installs everything, no `pip install`.

Built for University of Toronto courses that grade with PythonTA. Not affiliated with the University of Toronto or the PythonTA maintainers.

## Why

- **No install step.** PythonTA and everything it needs ship inside the extension. You only need Python 3.10 or newer, which the course already requires.
- **Matches the grader.** Course starter files end with `python_ta.check_all(config={...})`. The extension reads that block and applies the same config, so you don't get false positives like "forbidden import random" that the grader would never report.
- **Only PythonTA.** By default, Pylance and basedpyright problems are hidden so the Problems panel shows one source of truth and nothing overlaps. Autocomplete keeps working. One command turns it back.
- **Never runs your file.** Files are parsed, not executed.

## Install

1. Install [Python 3.10+](https://www.python.org/downloads/) if you haven't already.
2. Install **PythonTA Checker** from the VS Code Marketplace. The Python extension comes with it.
3. Problems appear when you open or save a file. With autosave on, they refresh about a second after you stop typing. Click **PyTA** on the bottom status bar to re-check.

**The extension only works in a trusted workspace.** VS Code asks you to trust a folder the first time you open it.

## Reading the squiggles

- **Red** is a PythonTA error. **Yellow** is everything else: warnings, style and convention messages. The grader reports both.
- Hover a squiggle and click the code (for example `E9999`) to open the PythonTA page for that message. It explains what is wrong and how to fix it.

## Commands

| Command | What it does |
| --- | --- |
| PythonTA: Check Current File (`Ctrl+Alt+T`, `Cmd+Alt+T` on macOS, `Ctrl+Alt+Shift+T` on Linux) | Save and check the current file now. |
| PythonTA: Toggle Only-PythonTA Problems | Show or hide Pylance and basedpyright problems. |
| PythonTA: Restart Server | Restart the checker, for example after installing a different Python. |
| PythonTA: Show Output Log | Open the PythonTA log. |

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `pythonta.hideOtherPythonDiagnostics` | `true` | Hide Pylance and basedpyright problems. Use the toggle command rather than editing this by hand. |
| `pythonta.runOnSave` | `true` | Check a file each time it is saved. |
| `pythonta.runOnOpen` | `true` | Check a file when it is opened. |
| `pythonta.configPath` | `""` | PythonTA config file to use when the file has no `check_all(config=...)` of its own. Relative to the workspace folder. |
| `pythonta.importStrategy` | `useBundled` | `useBundled` uses the PythonTA inside the extension. `fromEnvironment` prefers the PythonTA installed in your selected interpreter. |
| `pythonta.interpreter` | `""` | Path to a Python executable, if you want to override the one the Python extension picked. |

If you uninstall the extension while Only PythonTA is on, Pylance problems stay hidden, because VS Code gives extensions no chance to clean up. Run the toggle command first, or delete the two `analysis.ignore` lines from your `settings.json`.

## Other editors

### Zed

The Zed extension lives in [`zed/`](zed/). It is not in the Zed extension registry yet, so install it as a dev extension:

1. Install [Rust via rustup](https://rustup.rs), which Zed needs to compile a dev extension.
2. Clone this repository.
3. In Zed, open the Extensions page, click **Install Dev Extension**, and pick the `zed/` folder of the checkout.
4. Open a Python file. The extension downloads PythonTA and the checker from the latest GitHub release on first use, and finds a Python 3.10+ on its own. To use a specific Python, set:

```json
{
  "lsp": {
    "pyta-lsp": {
      "settings": { "interpreter": "/path/to/python" }
    }
  }
}
```

Zed runs every Python language server you have, so for Only PythonTA add:

```json
{
  "languages": {
    "Python": {
      "language_servers": ["pyta-lsp", "!basedpyright", "!ruff", "!pyright", "!ty", "!pylsp"]
    }
  }
}
```

[`zed/README.md`](zed/README.md) covers the other settings and where to find the log.

### Anything else

The checker is a standalone language server (`python -m pyta_lsp` over stdio), so any editor that speaks LSP can use it. Each GitHub release attaches `pyta-lsp-server-<version>.tar.gz`: extract it, put its `libs` directory on `PYTHONPATH`, and start `python -m pyta_lsp` with Python 3.10 or newer. If you want a specific editor supported, open a GitHub issue.

## Troubleshooting

If nothing appears, open **View > Output** and pick **PythonTA** from the dropdown. The log says which Python was found and what the checker did.

If the course config has a problem PythonTA complains about, you get an information message on line 1 naming the config file, so a broken config never fails silently.

Still stuck? [Open an issue](https://github.com/ThePoNGz/pyta-checker/issues) with the log and the file.

## Contributing

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e "server[dev]"     # POSIX: .venv/bin/python
.venv/Scripts/python scripts/bundle.py build             # builds bundled/libs, needed to run the extension
npm ci && npm test                                       # type-check, lint, unit tests
.venv/Scripts/python -m pytest server/tests -q           # server tests
```

## License

MIT. See `LICENSE`.

The extension bundles unmodified third-party Python packages; see `THIRD_PARTY_NOTICES.md` for the list and their licenses. PythonTA's package metadata declares MIT while its repository LICENSE file is GPL-3.0; this project redistributes the published wheel unchanged. See https://github.com/pyta-uoft/pyta.
