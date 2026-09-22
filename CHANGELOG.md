# Changelog

## 0.1.0 — 2026-09-22

- Check Python files with PythonTA on open, on save, and on command; results appear as squiggles and in the Problems panel with links to the docs.
- PythonTA and its dependencies are bundled; no pip install required.
- The `check_all(config=...)` block embedded in course files is honored.
- Optional Only-PythonTA mode hides Pylance and basedpyright diagnostics.
- Status bar item showing server and per-file state.
- Messages PythonTA reports against a config file are no longer shown on the checked file.
- Trailing-whitespace, `TODO` (fixme) and anomalous-backslash squiggles land on the right column on lines with non-ASCII text; mypy (E9951–E9956) squiggles no longer start one character to the right.
- Closing a tab while its check is running no longer stalls the server.
- `load_default_config=False` in a file's own `check_all(...)` is honoured.
- The mypy cache is per-user, so type-check messages no longer disappear on shared machines.
- Only-PythonTA: opening a window no longer restarts Pylance/basedpyright when nothing changed; the toggle reports whether the settings change actually took effect, in both directions, when a workspace setting outranks it; the first-run prompt honours "No".
- The server is no longer given the parent shell's `PYTHONHOME`/`VIRTUAL_ENV`/`CONDA_PREFIX`/`PYTHONSTARTUP`.
- Server shutdown is given time to clean up its check processes on restart.
