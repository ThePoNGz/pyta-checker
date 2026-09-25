#!/bin/bash
# Installs the repo dependencies at the start of a Claude Code cloud session.
# Local sessions exit right away so this never touches a developer machine.
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

set -u
cd "$CLAUDE_PROJECT_DIR" || exit 0

if [ ! -d node_modules ]; then
  npm ci || true
fi

if ! python3 -c "import pyta_lsp, pytest_lsp" >/dev/null 2>&1; then
  python3 -m pip install --break-system-packages -e "server[dev]" \
    || python3 -m pip install -e "server[dev]" \
    || true
fi

if command -v rustup >/dev/null 2>&1; then
  rustup target add wasm32-wasip2 || true
fi

exit 0
