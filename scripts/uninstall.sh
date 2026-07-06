#!/usr/bin/env bash
set -euo pipefail
ROOT="${MY_FREE_AGENTS_ROOT:-$HOME/.my-free-agents}"
BIN_DIR="${MY_FREE_AGENTS_BIN_DIR:-$HOME/.local/bin}"
case "$ROOT" in
  ""|"/"|"$HOME"|"$HOME/") printf 'Refusing unsafe root: %s\n' "${ROOT:-<empty>}" >&2; exit 1 ;;
esac
rm -f "$BIN_DIR/my-free-claudecode" "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-server-claudecode" "$BIN_DIR/my-claudecode" "$BIN_DIR/start-claudecode-server"
if [ "${1:-}" = "--keep-config" ]; then
  rm -rf "$ROOT/claudecode/free_claude_code" "$ROOT/claudecode/my_claudecode_python" "$ROOT/claudecode/bin" "$ROOT/claudecode/scripts" "$ROOT/claudecode/pyproject.toml" "$ROOT/claudecode/README.md"
else
  rm -rf "$ROOT"
fi
printf 'Removed My Free Agents.\n'
