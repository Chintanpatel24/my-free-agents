#!/usr/bin/env bash
set -euo pipefail

APP_NAME="My Free Agents"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLD_INSTALL_DIR="$HOME/.free-claude-code/app"
INSTALL_DIR="${MY_FREE_AGENTS_INSTALL_DIR:-$HOME/.my-free-agents/claudecode}"
BIN_DIR="${MY_FREE_AGENTS_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON:-python3}"

say(){ printf '\033[1;32m%s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m%s\033[0m\n' "$*"; }
err(){ printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { err "Python 3.10+ is required."; exit 1; }

case "$INSTALL_DIR" in
  ""|"/"|"$HOME"|"$HOME/") err "Refusing unsafe install directory: ${INSTALL_DIR:-<empty>}"; exit 1 ;;
esac

# Check for Claude Code
if ! command -v claude >/dev/null 2>&1; then
    warn "Claude Code CLI ('claude' command) not found. Please install it first for the best experience."
    warn "You can install it with: npm install -g @anthropic-ai/claude-code"
    printf '\033[1;34m%s\033[0m ' "Do you want to continue anyway? (y/N):"
    read -r CONTINUE_INSTALL < /dev/tty
    if [[ ! "$CONTINUE_INSTALL" =~ ^[Yy]$ ]]; then
        say "Installation cancelled."
        exit 0
    fi
fi

# Check for httpx
say "Checking Python HTTP dependency (httpx)..."
if ! "$PYTHON_BIN" -c "import httpx" >/dev/null 2>&1; then
    warn "Missing httpx for Python. It is required for the proxy."
    printf '\033[1;34m%s\033[0m ' "Would you like to install them now? (y/N):"
    read -r INSTALL_DEPS < /dev/tty
    if [[ "$INSTALL_DEPS" =~ ^[Yy]$ ]]; then
        "$PYTHON_BIN" -m pip install "httpx" || warn "Failed to install dependencies automatically. Please run: $PYTHON_BIN -m pip install httpx"
    else
        warn "Skipping dependency installation. Note that the server may not work correctly without them."
    fi
fi
if ! "$PYTHON_BIN" -c "import h2" >/dev/null 2>&1; then
    warn "Optional HTTP/2 package h2 is not installed. That is OK; HTTP/1.1 is the fast default."
fi

"$PYTHON_BIN" - <<'PY' || exit 1
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10+ is required. Found ' + sys.version.split()[0])
PY

# Migration logic
if [ -d "$OLD_INSTALL_DIR" ] && [ ! -d "$INSTALL_DIR" ]; then
    say "Migrating existing installation from $OLD_INSTALL_DIR to $INSTALL_DIR..."
    mkdir -p "$(dirname "$INSTALL_DIR")"
    cp -R "$OLD_INSTALL_DIR" "$INSTALL_DIR"
    warn "Migration complete. You may want to remove $OLD_INSTALL_DIR manually later."
fi

say "Installing $APP_NAME safely for the current user..."
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# Clean up old package name if it exists to avoid rsync/cp conflicts
rm -rf "$INSTALL_DIR/free_claude_code"

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

# Remove old command names to avoid confusion.
rm -f "$BIN_DIR/my-free-claudecode" "$BIN_DIR/my-claudecode-server" "$BIN_DIR/my-server-claudecode"

cat > "$BIN_DIR/start-claudecode-server" <<EOF
#!/usr/bin/env bash
export MY_FREE_AGENTS_HOME="$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR:\${PYTHONPATH:-}"
exec "$PYTHON_BIN" -c 'from my_claudecode_python.cli import main_server; main_server()' "\$@"
EOF
cat > "$BIN_DIR/my-claudecode" <<EOF
#!/usr/bin/env bash
export MY_FREE_AGENTS_HOME="$INSTALL_DIR"
export PYTHONPATH="$INSTALL_DIR:\${PYTHONPATH:-}"
exec "$PYTHON_BIN" -c 'from my_claudecode_python.cli import main_claude; main_claude()' "\$@"
EOF
chmod 700 "$BIN_DIR/start-claudecode-server" "$BIN_DIR/my-claudecode"

MY_FREE_AGENTS_HOME="$INSTALL_DIR" PYTHONPATH="$INSTALL_DIR" "$PYTHON_BIN" -c 'from my_claudecode_python.config import ensure_env, write_env_values; ensure_env(); write_env_values({}); print(ensure_env())' >/tmp/my-free-agents-env-path.txt
ENV_FILE="$(cat /tmp/my-free-agents-env-path.txt)"
rm -f /tmp/my-free-agents-env-path.txt
chmod 600 "$ENV_FILE" 2>/dev/null || true

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    SHELL_NAME="$(basename "${SHELL:-sh}")"
    PROFILE="$HOME/.profile"
    [ "$SHELL_NAME" = "zsh" ] && PROFILE="$HOME/.zshrc"
    [ "$SHELL_NAME" = "bash" ] && PROFILE="$HOME/.bashrc"
    if ! grep -q "export PATH=\"$BIN_DIR:" "$PROFILE" 2>/dev/null; then
      printf '\n# My Free Agents\nexport PATH="%s:$PATH"\n' "$BIN_DIR" >> "$PROFILE"
    fi
    warn "$BIN_DIR was added to $PROFILE. Restart your terminal or run: export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

say "Installed commands:"
printf '  %s\n' "$BIN_DIR/start-claudecode-server" "$BIN_DIR/my-claudecode"
say "Config file: $ENV_FILE"

# Check if API key already exists
EXISTING_API_KEY=""
if [ -f "$ENV_FILE" ]; then
    EXISTING_API_KEY=$(grep "^NVIDIA_NIM_API=" "$ENV_FILE" | cut -d'=' -f2)
fi

if [[ -n "$EXISTING_API_KEY" && "$EXISTING_API_KEY" != "your-api-key" && -z "${EXISTING_API_KEY// }" ]]; then
    # Prompt for API Key (read from /dev/tty to support piped installation)
    printf '\n\033[1;34m%s\033[0m ' "Please enter your NVIDIA NIM API key (Press Enter to skip and do it manually later):"
    read -r USER_API_KEY < /dev/tty
elif [[ -n "$EXISTING_API_KEY" && "$EXISTING_API_KEY" != "your-api-key" ]]; then
    say "Existing API key found. Skipping prompt."
    USER_API_KEY="$EXISTING_API_KEY"
else
    # Prompt for API Key (read from /dev/tty to support piped installation)
    printf '\n\033[1;34m%s\033[0m ' "Please enter your NVIDIA NIM API key (Press Enter to skip and do it manually later):"
    read -r USER_API_KEY < /dev/tty
fi

if [[ -n "$USER_API_KEY" && "$USER_API_KEY" != "$EXISTING_API_KEY" ]]; then
    say "Validating API key..."
    # Simple validation check using curl to fetch models
    if ! command -v curl >/dev/null 2>&1; then
        warn "curl is not available, so the API key could not be validated."
        HTTP_CODE=""
    else
        HTTP_CODE=$(curl -sS --connect-timeout 8 --max-time 20 -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $USER_API_KEY" "https://integrate.api.nvidia.com/v1/models" || true)
    fi

    if [ "$HTTP_CODE" = "200" ]; then
        MY_FREE_AGENTS_API_KEY="$USER_API_KEY" MY_FREE_AGENTS_HOME="$INSTALL_DIR" PYTHONPATH="$INSTALL_DIR" "$PYTHON_BIN" -c 'import os; from my_claudecode_python.config import write_env_values; write_env_values({"NVIDIA_NIM_API": os.environ["MY_FREE_AGENTS_API_KEY"]})'
        say "API key validated and saved."
    else
        warn "API key validation failed (HTTP $HTTP_CODE). You can set it later in $ENV_FILE or via the admin UI."
    fi
elif [[ -z "$USER_API_KEY" ]]; then
    warn "No API key entered. You can set it later in $ENV_FILE or via the admin UI."
fi

printf '\nNext steps:\n'
printf '  1. Start server: start-claudecode-server\n'
printf '  2. Open admin UI (optional): http://127.0.0.1:2424/admin\n'
printf '  3. New terminal: my-claudecode\n'
