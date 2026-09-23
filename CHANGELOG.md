# Changelog

## 0.1.0 — 2026-09-22

- Check Python files with PythonTA on open, on save, and on command; results appear as squiggles and in the Problems panel with links to the docs.
- PythonTA and its dependencies are bundled; no pip install required.
- The `check_all(config=...)` block embedded in course files is honored.
- Optional Only-PythonTA mode hides Pylance and basedpyright diagnostics.
- Status bar item showing server and per-file state.
- Messages PythonTA reports against a config file are no longer squiggled as the student's; they appear as one information message on line 1 naming the config file.
- Trailing-whitespace, `TODO` (fixme) and anomalous-backslash squiggles land on the right column on lines with non-ASCII text; mypy (E9951–E9956) squiggles no longer start one character to the right.
- Closing a tab while its check is running no longer stalls the server.
- `load_default_config=False` in a file's own `check_all(...)` is honoured.
- The mypy cache is per-user, so type-check messages no longer disappear on shared machines.
- Only-PythonTA: opening a window no longer restarts Pylance/basedpyright when nothing changed; the toggle reports whether the settings change actually took effect, in both directions, when a workspace setting outranks it.
- The server is no longer given the parent shell's `PYTHONHOME`/`VIRTUAL_ENV`/`CONDA_PREFIX`/`PYTHONSTARTUP`.
- Server shutdown is given time to clean up its check processes on restart.
- Type-check messages (E9951–E9956) now appear on Windows for unsaved and non-package files; a course `config/.pylintrc` beside the file and a `config` passed by position are honoured; a file with a non-UTF-8 coding cookie, mixed line endings, or a form feed is checked and positioned correctly.
- A student file named after a standard-library module (`random.py`, `string.py`, ...) beside the checked file is no longer imported by the checker.
- Closing the window with several files open no longer leaves check processes running; a check that fails before it starts no longer leaves the status bar spinning.
- Restart during the client's own crash recovery no longer leaves a second server running; an interpreter set in `pythonta.interpreter` that cannot run is reported once instead of silently replaced.
- Only-PythonTA: a workspace setting equal to the hide-all value no longer reads as blocking; folder settings in multi-root workspaces are seen; a second window no longer overwrites the saved settings snapshot.
- Linux keybinding is `Ctrl+Alt+Shift+T` (GNOME uses `Ctrl+Alt+T` for the terminal).
- Only-PythonTA is on by default. The first window says so with a one-time notice and a "Show them again" action, instead of asking a yes/no question.
