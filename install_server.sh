#!/usr/bin/env bash
set -euo pipefail

say(){ printf '\033[1;32m%s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m%s\033[0m\n' "$*"; }
err(){ printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

echo "------------------------------------------------"
echo "  My Free Agents - Multi-Language Installation"
echo "------------------------------------------------"
echo "Select the proxy server language:"
echo "1) Python (Default) - Best compatibility & easy setup"
echo "2) Go - High performance, efficient concurrency"
echo "3) Rust - Maximum safety, speed & memory efficiency"
echo "4) C++ - Ultra-low latency, bare-metal performance"
printf "Enter choice (1-4) [1]: "
read -r SERVER_CHOICE < /dev/tty
SERVER_CHOICE=${SERVER_CHOICE:-1}

echo ""
echo "Select the configuration/admin handling language:"
echo "1) Python (Default) - Standard handling"
echo "2) Native - Use selected server language for admin UI"
printf "Enter choice (1-2) [1]: "
read -r HANDLING_CHOICE < /dev/tty
HANDLING_CHOICE=${HANDLING_CHOICE:-1}

INSTALL_DIR="${MY_FREE_AGENTS_INSTALL_DIR:-$HOME/.my-free-agents/claudecode}"
BIN_DIR="${MY_FREE_AGENTS_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$BIN_DIR"

case $SERVER_CHOICE in
  1)
    say "Installing Python server..."
    bash scripts/install.sh
    ;;
  2)
    say "Installing Go server..."
    if ! command -v go >/dev/null 2>&1; then err "Go is required."; exit 1; fi
    cd my_claudecode_go && go build -o "$BIN_DIR/go-proxy" .
    cat > "$BIN_DIR/start-claudecode-server" <<EOF
#!/usr/bin/env bash
exec "$BIN_DIR/go-proxy" "\$@"
EOF
    chmod +x "$BIN_DIR/start-claudecode-server"
    ;;
  3)
    say "Installing Rust server..."
    if ! command -v cargo >/dev/null 2>&1; then err "Rust/Cargo is required."; exit 1; fi
    cd my_claudecode_rust && cargo build --release
    cp target/release/my_claudecode_rust "$BIN_DIR/rust-proxy"
    cat > "$BIN_DIR/start-claudecode-server" <<EOF
#!/usr/bin/env bash
exec "$BIN_DIR/rust-proxy" "\$@"
EOF
    chmod +x "$BIN_DIR/start-claudecode-server"
    ;;
  4)
    say "Installing C++ server..."
    if ! command -v cmake >/dev/null 2>&1; then err "CMake is required."; exit 1; fi
    mkdir -p my_claudecode_cpp/build
    cd my_claudecode_cpp/build && cmake .. && make -j$(nproc)
    cp my_claudecode_cpp "$BIN_DIR/cpp-proxy"
    cat > "$BIN_DIR/start-claudecode-server" <<EOF
#!/usr/bin/env bash
exec "$BIN_DIR/cpp-proxy" "\$@"
EOF
    chmod +x "$BIN_DIR/start-claudecode-server"
    ;;
  *)
    err "Invalid choice."; exit 1 ;;
esac

say "Installation complete! Start with: start-claudecode-server"
