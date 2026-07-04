#!/usr/bin/env bash
set -euo pipefail
ROOT="${MY_FREE_AGENTS_ROOT:-$HOME/.my-free-agents}"
BIN_DIR="${MY_FREE_AGENTS_BIN_DIR:-$HOME/.local/bin}"
rm -f "$BIN_DIR/my-free-claudecode" "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-server-claudecode" "$BIN_DIR/my-claudecode" "$BIN_DIR/start-claudecode-server"
if [ "${1:-}" = "--keep-config" ]; then
  rm -rf "$ROOT/claudecode/free_claude_code" "$ROOT/claudecode/bin" "$ROOT/claudecode/scripts" "$ROOT/claudecode/pyproject.toml" "$ROOT/claudecode/README.md"
else
  rm -rf "$ROOT"
fi
printf 'Removed My Free Agents.\n'
