# PythonTA for Zed

See exactly what [PythonTA](https://www.cs.toronto.edu/~david/pyta/) will flag, as squiggles in Zed. The extension runs the same language server as the [VS Code extension](https://github.com/ThePoNGz/pyta-checker), so the `check_all(config=...)` block at the end of a course file is honoured and the grader's config is the one you see.

Not affiliated with the University of Toronto or the PythonTA maintainers.

## Install

The extension is not in the Zed extension registry yet, so install it as a dev extension:

1. Install [Rust via rustup](https://rustup.rs). Zed compiles dev extensions on your machine.
2. Clone https://github.com/ThePoNGz/pyta-checker.
3. In Zed, open the Extensions page (`zed: extensions`), click **Install Dev Extension**, and pick the `zed/` folder of the checkout.
4. Open a Python file. The first time, the extension downloads the server (PythonTA and everything it needs) from the latest GitHub release of pyta-checker into Zed's work directory for the extension. Nothing is installed into your Python.

Until a release newer than v0.1.0 is tagged there is no server to download, and the extension says so. In the meantime build the server yourself with `python scripts/bundle.py build` in the checkout and set `serverDir` (below) to its `bundled/libs`.

You need Python 3.10 or newer. The extension looks for it in this order: the `interpreter` setting, `.venv/bin/python` (`.venv\Scripts\python.exe` on Windows) in the project, then `python3` and `python` on your PATH (on Windows `python`, `python3`, then the `py` launcher). The first one that runs and is 3.10 or newer is used; older or broken ones are skipped and listed if nothing fits. Zed does not hand its selected Python toolchain to extensions, so set `interpreter` if the one it finds is not the one you want.

## Settings

Both keys live under `lsp.pyta-lsp.settings` in your Zed settings (`zed: open settings`):

```json
{
  "lsp": {
    "pyta-lsp": {
      "settings": {
        "interpreter": "/path/to/python",
        "serverDir": "/path/to/pyta-checker/bundled/libs"
      },
      "initialization_options": {
        "runOnSave": true,
        "runOnOpen": true,
        "configPath": ""
      }
    }
  }
}
```

| Key | Meaning |
| --- | --- |
| `interpreter` | A Python executable: an absolute path (`~` is not expanded), or a bare name such as `python3.12` to look up on your PATH. When set, it is the only one tried, and one that does not run or is older than 3.10 is reported instead of silently replaced. |
| `serverDir` | Path to a local `libs` directory holding the server and its dependencies. Skips the download. Build one with `python scripts/bundle.py build` in a checkout and point this at its `bundled/libs`. |

`initialization_options` are the checker's own settings: `runOnSave`, `runOnOpen` and `configPath` mean the same as the `pythonta.*` settings in the VS Code extension. `configPath` is a PythonTA config file used when the file has no `check_all(config=...)` of its own, relative to the project root. Put them there, not under `settings`, which only holds the two keys above.

## Only PythonTA

Zed runs every Python language server you have installed. To see only PythonTA problems, list it as the one server to run for Python:

```json
{
  "languages": {
    "Python": {
      "language_servers": ["pyta-lsp"]
    }
  }
}
```

A list without `"..."` runs only what it names. To keep the others, for example basedpyright for completions and go-to-definition, and drop just one, use `["pyta-lsp", "...", "!ruff"]`.

## Reading the log

Two logs matter. `zed: open log` is where the extension reports why it could not find a Python or fetch the server. `dev: open language server logs` (pick `pyta-lsp`) shows what the server printed: which Python it runs under, and any file it could not check and why. A successful check prints nothing there. When the newest release could not be fetched and an earlier download is used instead, the server log says so at startup. For more, quit Zed and start it from a terminal with `zed --foreground`.

If the extension reports that no Python was found, or that the one it found is too old, set `interpreter`. If it reports that the server could not be downloaded, check your connection, or set `serverDir` to a local build.

## License

MIT. See `LICENSE`. The server this extension downloads bundles unmodified third-party Python packages; see `THIRD_PARTY_NOTICES.md` in the repository root.
