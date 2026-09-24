# Zed extension plan

Temporary file. Delete it in the last commit before the PR is marked ready.

Read `CLAUDE.md` first. Work on the `zed-extension` branch. Open a draft PR to `main` titled "Zed extension" as soon as the first task is committed so CI and the Greptile app run on every push. Do not merge it.

## What exists today

- The VS Code extension launches the server as `python -m pyta_lsp` over stdio with `PYTHONPATH` set to `bundled/libs` and cwd set to the extension folder. See `src/client.ts` and `src/serverEnv.ts` for the exact env and `src/settings.ts` for the initialization options JSON.
- `python scripts/bundle.py build` produces `bundled/libs`: pure Python wheels only, one copy for every OS and Python 3.10 to 3.14. It is not committed.
- `release.yml` runs on a `v*` tag, builds the VSIX and attaches it to a GitHub release. Marketplace upload is manual.
- The server runs each check in a subprocess from a staging dir and sets `PYTHONSAFEPATH=1` so a student file named like a stdlib module cannot shadow it. Python 3.10 has no SAFEPATH and keeps that residual.

## How Zed extensions work (verified against zed.dev docs, September 2026)

- A Zed extension is a Rust crate compiled to `wasm32-wasip2` against the `zed_extension_api` crate. Zed builds it on install. Check crates.io for the newest version before pinning it.
- Files: `extension.toml`, `Cargo.toml` (crate-type cdylib), `src/lib.rs`, `LICENSE`, `README.md`.
- Python is built into Zed, so the extension only registers a language server for the existing `Python` language:
  ```toml
  [language_servers.pyta-lsp]
  name = "PythonTA"
  languages = ["Python"]
  ```
- The `zed::Extension` trait method `language_server_command` returns `zed::Command { command, args, env }`. `language_server_initialization_options` and `language_server_workspace_configuration` forward what the user put under `lsp.pyta-lsp.initialization_options` and `lsp.pyta-lsp.settings` in Zed settings, read with `zed::settings::LspSettings::for_worktree`.
- Available API: `worktree.which(name)`, `worktree.root_path()`, `worktree.read_text_file(path)`, `worktree.shell_env()`, `zed::latest_github_release(repo, options)`, `zed::download_file(url, path, DownloadedFileType::GzipTar)`, `zed::set_language_server_installation_status`, `zed::current_platform()`, `zed::process::Command::new(program).args(..).output()`. Paths given to `download_file` are relative to the extension work dir, which is also the process cwd, so `std::env::current_dir()` gives the absolute base.
- Capabilities must be declared in `extension.toml`:
  ```toml
  [[capabilities]]
  kind = "download_file"
  host = "github.com"
  path = ["ThePoNGz", "pyta-checker", "**"]

  [[capabilities]]
  kind = "process:exec"
  command = "*"
  args = ["**"]
  ```
- Zed does not pass the selected Python toolchain to extension language servers. The docs say so explicitly. The extension has to find an interpreter itself.
- Users pick which servers run per language. Only PythonTA in Zed is this snippet in the user's settings, and an extension cannot set it:
  ```json
  "languages": { "Python": { "language_servers": ["pyta-lsp", "!basedpyright", "!ruff", "!pyright", "!ty", "!pylsp"] } }
  ```
- Zed starts language servers with the project root as cwd. Set `PYTHONSAFEPATH=1` in the command env so a student file at the root cannot shadow stdlib inside the server process.
- Registry rules: extension id must end in `-lsp` or `-language-server` (`pyta-lsp` is free), the server must not be bundled inside the extension, an accepted license must be present, and the extension is published by a PR to zed-industries/extensions adding this repo as a submodule with `path = "zed"`. The owner opens that PR, not you.
- Docs: https://zed.dev/docs/extensions/languages, https://zed.dev/docs/extensions/capabilities, https://zed.dev/docs/extensions/publishing/prerequisites, https://zed.dev/docs/languages/python, https://docs.rs/zed_extension_api

## Tasks, in order

### 1. Server tarball on releases
- Add a `tarball` command to `scripts/bundle.py` that takes an output path and writes `pyta-lsp-server-<version>.tar.gz` containing one top level `libs/` directory: the contents of `bundled/libs` plus the `pyta_lsp` package installed into it. One `PYTHONPATH` entry must be enough to run `python -m pyta_lsp`.
- The version comes from `server/pyproject.toml`.
- Add a step to `release.yml` that builds it after `bundle.py build` and uploads it to the same GitHub release alongside the VSIX. Keep the release step idempotent.
- Add a CI check in the bundle job that extracts the tarball into a temp dir and runs `PYTHONPATH=<tmp>/libs python -c "import pyta_lsp, python_ta, pygls"` plus a real `initialize` round trip against the server started from an unrelated cwd. Tests for the new bundle.py code go in `server/tests` or a new `scripts/tests` dir, whichever the existing layout suggests.

### 2. Server cwd independence
- Confirm with a test that the server works when started from a directory that is not the extension folder, including a directory that contains a file named `json.py`, with `PYTHONSAFEPATH=1` set. Fix anything that assumed the old cwd.

### 3. The `zed/` folder
- `extension.toml`: id `pyta-lsp`, name `PythonTA`, version `0.1.0`, `schema_version = 1`, authors `["ThePong"]`, description, repository `https://github.com/ThePoNGz/pyta-checker`, the language server entry and the two capabilities above.
- `Cargo.toml`: package `pyta_lsp_zed` or similar, `crate-type = ["cdylib"]`, newest `zed_extension_api`. Commit `Cargo.lock`.
- `src/lib.rs` behaviour:
  1. Read `lsp.pyta-lsp.settings`. Supported keys: `interpreter` (path to a Python executable) and `serverDir` (path to a local `libs` directory, skips the download; this is how the owner tests before a release exists).
  2. Interpreter order: `interpreter` setting, then `.venv/bin/python` or `.venv/Scripts/python.exe` under the worktree root, then `python` before `python3` on Windows and `python3` before `python` elsewhere via `worktree.which`. Probe the chosen one with `process::Command` running `-c "import sys; print(sys.version_info[0], sys.version_info[1])"` and refuse anything below 3.10 with a message that says what was found and what is needed.
  3. Server: if `serverDir` is set, use it. Otherwise call `latest_github_release("ThePoNGz/pyta-checker", require_assets)`, pick the asset whose name starts with `pyta-lsp-server-`, download it as GzipTar into `pyta-lsp-server-<tag>/` under the work dir unless that dir already exists, report progress with `set_language_server_installation_status`, and remove older `pyta-lsp-server-*` dirs. If the download fails but an older dir exists, use it.
  4. Return `Command { command: <python>, args: ["-m", "pyta_lsp"], env: [("PYTHONPATH", <abs libs dir>), ("PYTHONSAFEPATH", "1"), ("PYTHONUTF8", "1")] }`.
  5. Forward `initialization_options` and `settings` from `LspSettings` unchanged.
- Keep the decision logic (interpreter ordering, version parsing, asset picking, directory naming) in a module with no `zed_extension_api` calls so it has native `cargo test` unit tests. Only the thin glue touches the API.
- `zed/README.md`: install as a dev extension, the two settings keys, the Only PythonTA snippet, and how to read the Zed log (`zed: open log`).
- `zed/LICENSE`: copy of the repo LICENSE.
- Add `zed/**`, `.claude/**` and `ZED_PLAN.md` to `.vscodeignore` if not already there.

### 4. CI job for the Zed extension
- New job in `ci.yml` on ubuntu: install the `wasm32-wasip2` target, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test` (native), `cargo build --release --target wasm32-wasip2`, all with `--manifest-path zed/Cargo.toml`. Cache cargo.

### 5. Docs
- README: in the "Other editors" section add Zed. Until the registry PR is merged the install path is "Install Dev Extension" pointing at the `zed/` folder of a checkout. Include the Only PythonTA snippet and the `interpreter` setting.
- CHANGELOG: an entry under the next version.

### 6. Review loop
- Push, make sure the draft PR exists, wait for CI (`gh pr checks --watch`) and for the Greptile app comment on the PR (poll `gh api repos/ThePoNGz/pyta-checker/issues/<pr>/comments` and `pulls/<pr>/comments` for the `greptile-apps` user). Fix real findings, push, repeat until a pass adds nothing new. Do not reply to Greptile on GitHub.
- Ask for a second opinion from a reviewer subagent on the Rust code before the last push.

### 7. Handoff
- Delete `ZED_PLAN.md` in the final commit. Leave the PR as a draft.
- Finish with a message that lists: what was built, what CI and Greptile said, anything unverified, and the exact local test steps for the owner (below) with the `serverDir` value they need to set to the `bundled/libs` of their checkout.

## Local test the owner does (not you)

1. `python scripts/bundle.py build` in the checkout.
2. Zed: Extensions, Install Dev Extension, pick the `zed/` folder.
3. Settings: `lsp.pyta-lsp.settings.serverDir` pointing at the checkout's `bundled/libs`, plus the Only PythonTA snippet.
4. Open a Python file from a course project, break something, save, check the squiggles and `zed: open log`.
5. Remove `serverDir` after the next release is tagged and confirm the download path works.
