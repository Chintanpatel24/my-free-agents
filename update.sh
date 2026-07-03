#!/usr/bin/env bash
set -euo pipefail
SCRIPT_SOURCE="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" 2>/dev/null && pwd || pwd)"
if [ -f "$SCRIPT_DIR/scripts/install.sh" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
  exec bash "$SCRIPT_DIR/scripts/install.sh" "$@"
fi
REPO_URL="${FREE_CLAUDE_CODE_REPO:-https://github.com/Chintanpatel24/my-free-claudecode.git}"
BRANCH="${FREE_CLAUDE_CODE_BRANCH:-main}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
command -v git >/dev/null 2>&1 || { echo "git is required for update." >&2; exit 1; }
git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$TMP_DIR/repo"
exec bash "$TMP_DIR/repo/scripts/install.sh" "$@"
