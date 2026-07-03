#!/usr/bin/env bash
set -euo pipefail
ROOT="${FREE_CLAUDE_CODE_ROOT:-$HOME/.free-claude-code}"
BIN_DIR="${FREE_CLAUDE_CODE_BIN_DIR:-$HOME/.local/bin}"
rm -f "$BIN_DIR/my-free-claudecode" "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-claudecode"
if [ "${1:-}" = "--keep-config" ]; then
  rm -rf "$ROOT/app/free_claude_code" "$ROOT/app/bin" "$ROOT/app/scripts" "$ROOT/app/pyproject.toml" "$ROOT/app/README.md"
else
  rm -rf "$ROOT"
fi
printf 'Removed My ClaudeCode NVIDIA NIM Proxy.\n'
