#!/usr/bin/env bash
set -euo pipefail

APP_NAME="My ClaudeCode NVIDIA NIM Proxy"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${FREE_CLAUDE_CODE_INSTALL_DIR:-$HOME/.free-claude-code/app}"
BIN_DIR="${FREE_CLAUDE_CODE_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON:-python3}"

say(){ printf '\033[1;32m%s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m%s\033[0m\n' "$*"; }
err(){ printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { err "Python 3.10+ is required."; exit 1; }
"$PYTHON_BIN" - <<'PY' || exit 1
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10+ is required. Found ' + sys.version.split()[0])
PY

say "Installing $APP_NAME safely for the current user..."
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '.env' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude '.venv' --exclude 'dist' --exclude 'build' --exclude '*.egg-info' \
    "$SRC_DIR/" "$INSTALL_DIR/"
else
  TMP_COPY="$INSTALL_DIR.tmp.$$"
  rm -rf "$TMP_COPY"
  mkdir -p "$TMP_COPY"
  cp -R "$SRC_DIR/." "$TMP_COPY/"
  rm -rf "$TMP_COPY/.git" "$TMP_COPY/.env" "$TMP_COPY/__pycache__" "$TMP_COPY/.venv" "$TMP_COPY/dist" "$TMP_COPY/build" "$TMP_COPY"/*.egg-info
  find "$TMP_COPY" -name '*.pyc' -delete 2>/dev/null || true
  find "$TMP_COPY" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
  if [ -f "$INSTALL_DIR/.env" ]; then cp "$INSTALL_DIR/.env" "$TMP_COPY/.env"; fi
  rm -rf "$INSTALL_DIR"
  mv "$TMP_COPY" "$INSTALL_DIR"
fi

chmod -R go-rwx "$INSTALL_DIR" 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh "$INSTALL_DIR/install.sh" "$INSTALL_DIR/uninstall.sh" "$INSTALL_DIR/bin/"* 2>/dev/null || true

# Remove old command name from previous versions to avoid confusion.
rm -f "$BIN_DIR/my-free-claudecode"

cat > "$BIN_DIR/my-claudecode-server" <<EOF
#!/usr/bin/env bash
export FREE_CLAUDE_CODE_HOME="$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR:\${PYTHONPATH:-}"
exec "$PYTHON_BIN" -c 'from free_claude_code.cli import main_server; main_server()' "\$@"
EOF
cat > "$BIN_DIR/my-claudecode" <<EOF
#!/usr/bin/env bash
export FREE_CLAUDE_CODE_HOME="$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR:\${PYTHONPATH:-}"
exec "$PYTHON_BIN" -c 'from free_claude_code.cli import main_claude; main_claude()' "\$@"
EOF
chmod 700 "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-claudecode"

FREE_CLAUDE_CODE_HOME="$INSTALL_DIR" PYTHONPATH="$INSTALL_DIR" "$PYTHON_BIN" -c 'from free_claude_code.config import ensure_env, write_env_values; ensure_env(); write_env_values({}); print(ensure_env())' >/tmp/free-claude-code-env-path.txt
ENV_FILE="$(cat /tmp/free-claude-code-env-path.txt)"
rm -f /tmp/free-claude-code-env-path.txt
chmod 600 "$ENV_FILE" 2>/dev/null || true

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    SHELL_NAME="$(basename "${SHELL:-sh}")"
    PROFILE="$HOME/.profile"
    [ "$SHELL_NAME" = "zsh" ] && PROFILE="$HOME/.zshrc"
    [ "$SHELL_NAME" = "bash" ] && PROFILE="$HOME/.bashrc"
    if ! grep -q "export PATH=\"$BIN_DIR:" "$PROFILE" 2>/dev/null; then
      printf '\n# My ClaudeCode NVIDIA NIM Proxy\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$PROFILE"
    fi
    warn "$BIN_DIR was added to $PROFILE. Restart your terminal or run: export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

say "Installed commands:"
printf '  %s\n' "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-claudecode"
say "Config file: $ENV_FILE"

# Prompt for API Key
printf '\n\033[1;34m%s\033[0m ' "Please enter your NVIDIA NIM API key:"
read -r USER_API_KEY

if [ -n "$USER_API_KEY" ]; then
    say "Validating API key..."
    # Simple validation check using curl to fetch models
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $USER_API_KEY" "https://integrate.api.nvidia.com/v1/models")

    if [ "$HTTP_CODE" = "200" ]; then
        FREE_CLAUDE_CODE_HOME="$INSTALL_DIR" PYTHONPATH="$INSTALL_DIR" "$PYTHON_BIN" -c "from free_claude_code.config import write_env_values; write_env_values({'NVIDIA_NIM_API': '$USER_API_KEY'})"
        say "API key validated and saved."
    else
        warn "API key validation failed (HTTP $HTTP_CODE). You can set it later in $ENV_FILE or via the admin UI."
    fi
else
    warn "No API key entered. You can set it later in $ENV_FILE or via the admin UI."
fi

printf '\nNext steps:\n'
printf '  1. Start server: my-claudecode-server\n'
printf '  2. Open admin UI (optional): http://127.0.0.1:2424/admin\n'
printf '  3. New terminal: my-claudecode\n'
