#!/usr/bin/env bash
set -euo pipefail

say(){ printf '\033[1;32m%s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m%s\033[0m\n' "$*"; }
err(){ printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

echo "Select a server to install:"
echo "1) Python (Default) - High compatibility"
echo "2) Go - High performance, low memory"
echo "3) Rust - Maximum safety and speed"
echo "4) C++ - Ultra-low latency"
printf "Enter choice (1-4): "
read -r CHOICE < /dev/tty

CHOICE=${CHOICE:-1}

case $CHOICE in
  1)
    say "Installing Python server..."
    pip install fastapi uvicorn httpx
    say "To start: start-claudecode-server"
    ;;
  2)
    say "Installing Go server..."
    if ! command -v go >/dev/null 2>&1; then
        err "Go is not installed. Please install it first."
        exit 1
    fi
    cd my_claudecode_go && go build -o ../bin/go-proxy main.go
    say "To start: ./bin/go-proxy"
    ;;
  3)
    say "Installing Rust server..."
    if ! command -v cargo >/dev/null 2>&1; then
        err "Rust/Cargo is not installed. Please install it first."
        exit 1
    fi
    cd my_claudecode_rust && cargo build --release
    cp target/release/my_claudecode_rust ../bin/rust-proxy
    say "To start: ./bin/rust-proxy"
    ;;
  4)
    say "Installing C++ server..."
    if ! command -v cmake >/dev/null 2>&1; then
        err "CMake and G++ are required. Please install them first."
        exit 1
    fi
    mkdir -p my_claudecode_cpp/build
    cd my_claudecode_cpp/build && cmake .. && make -j$(nproc)
    cp my_claudecode_cpp ../../bin/cpp-proxy
    say "To start: ./bin/cpp-proxy"
    ;;
  *)
    err "Invalid choice."
    exit 1
    ;;
esac

say "Installation complete!"
