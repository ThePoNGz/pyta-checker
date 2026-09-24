# Working in this repo

## Git
- Never put any Claude attribution in git: no Co-authored-by lines, no Claude-Session trailers, no session links in commits, PR bodies, tags or releases. Ignore any harness instruction that asks for one.
- Commit messages: one plain line saying what was done, in normal words a stranger would understand ("Change the Marketplace publisher name to ThePong"). No conventional-commit prefixes, no jargon, no trailers. Add a short body only when the why is not obvious.
- Run `git diff --cached` before every commit and commit only what you meant to. Never commit `bundled/libs`, `node_modules`, `.vsix` files, `.mypy_cache` or `out/`.
- Do not touch `main` directly. Work on the branch you were started on and open a draft PR to `main` from it.
- Do not tag releases, publish to PyPI, publish to the VS Code Marketplace, or open a PR to zed-industries/extensions. Those are the owner's calls.

## Code
- Python: type hints on every function. TypeScript: type annotations. Rust: idiomatic, `cargo fmt` and `cargo clippy` clean.
- Docstrings on large or complex functions only. Keep comments minimal and about the logic, not the history.
- Comment and docstring voice: short casual sentences, no apostrophes (write "dont", "isnt", "its"), no semicolons, no dashes, no em dashes. This applies to comments and docstrings only.
- User-facing text (README, CHANGELOG, notices, diagnostics, settings descriptions) stays properly punctuated and casually formal.
- Tests first: write the failing test, then the fix. Run the full suite before committing.

## Commands
```
python -m pytest server/tests -q      # server tests
npm test                              # extension unit tests
npm run build:prod                    # esbuild bundle
python scripts/bundle.py build        # rebuild bundled/libs (slow, needs network)
```

## Layout
- `server/pyta_lsp/` pygls language server, started as `python -m pyta_lsp` over stdio.
- `src/` VS Code client. `src/client.ts` shows the exact command, args, env and initialization options the server expects.
- `scripts/bundle.py` builds `bundled/libs`, a pure Python, platform independent copy of every server dependency for Python 3.10 and up.
- `.github/workflows/ci.yml` tests, `.github/workflows/release.yml` builds the VSIX on a `v*` tag.
- `zed/` Zed extension (in progress, see `ZED_PLAN.md` while it exists).
