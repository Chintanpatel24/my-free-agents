from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ensure_env, env_path, get_provider, load_env, local_base_url, write_env_values
from .server import run_server


def cmd_server(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="start-claudecode-server", description="Start/manage the NVIDIA NIM local proxy for Claude Code.")
    parser.add_argument("--init", action="store_true", help="create .env if missing")
    parser.add_argument("--doctor", action="store_true", help="check installation and config")
    parser.add_argument("--set-key", help="save NVIDIA_NIM_API in .env")
    parser.add_argument("--model", help="override NVIDIA NIM model for this server run only")
    parser.add_argument("--host", help="override HOST for this run")
    parser.add_argument("--port", type=int, help="override PORT for this run")
    args = parser.parse_args(argv)

    if args.init:
        p = ensure_env()
        print(f"Config ready: {p}")
        print(f"Edit it manually or open http://127.0.0.1:{args.port or 2424}/admin after starting the server.")
        return 0

    ensure_env()
    if args.model:
        os.environ["NVIDIA_NIM_MODEL"] = args.model
    if args.set_key:
        write_env_values({"NVIDIA_NIM_API": args.set_key})
        print(f"Saved NVIDIA_NIM_API to {env_path()}")
        return 0

    if args.doctor:
        return doctor()

    values = load_env()
    host = args.host or values.get("HOST", "127.0.0.1")
    port = args.port or int(values.get("PORT", "2424") or "2424")
    provider = get_provider(values)
    if provider.needs_key and (not provider.api_key or "your-key" in provider.api_key or provider.api_key == "your-api-key"):
        print(f"Missing NVIDIA_NIM_API. Set it in {env_path()} or run:", file=sys.stderr)
        print("  start-claudecode-server --set-key YOUR_NVIDIA_NIM_KEY", file=sys.stderr)
        return 2
    httpd = run_server(host, port)
    print("\n✅ My ClaudeCode NVIDIA NIM server is running")
    print(f"Provider: {provider.name}")
    print(f"Model:    {provider.model}")
    print(f"Server:   http://{host}:{port}")
    print(f"Admin:    http://{host}:{port}/admin")
    print("\nOpen another terminal and run: my-claudecode\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()
    return 0


def doctor() -> int:
    values = load_env()
    provider = get_provider(values)
    print("My ClaudeCode Server doctor")
    print("--------------------------")
    print(f"Python: {sys.version.split()[0]}")
    print(f"App home: {env_path().parent}")
    print(f".env: {env_path()} {'OK' if env_path().exists() else 'MISSING'}")
    print(f"Server URL: {local_base_url(values)}")
    print(f"Provider: {provider.name} only")
    print(f"Provider base URL: {provider.base_url or 'MISSING'}")
    print(f"Provider model: {provider.model or 'MISSING'}")
    key_ok = bool(provider.api_key and "your-key" not in provider.api_key and provider.api_key != "your-api-key")
    key_state = "OK" if key_ok else "MISSING/PLACEHOLDER"
    print(f"Provider API key: {key_state}")
    claude = values.get("CLAUDE_BINARY", "claude")
    found = shutil.which(claude)
    print(f"Claude Code binary '{claude}': {found or 'NOT FOUND'}")
    print("\nIf config is missing: start-claudecode-server --init")
    return 0


def cmd_claude(argv=None) -> int:
    values = load_env()
    provider = get_provider(values)
    base = local_base_url(values)
    claude = values.get("CLAUDE_BINARY", "claude")
    exe = shutil.which(claude) or claude
    env = os.environ.copy()
    env.update(values)
    env["ANTHROPIC_BASE_URL"] = base
    env["ANTHROPIC_API_KEY"] = "sk-ant-abc123not-needed-local-proxy"
    # Bypassing Claude Code login checks.
    env["CLAUDE_CODE_SKIP_LOGIN"] = "true"
    env["CLAUDE_CODE_USE_LOCAL_PROXY"] = "true"
    # Force real NVIDIA NIM defaults. Do not keep a user's old Anthropic model
    # env vars, because that can make Claude Code show/use Claude models.
    if provider.model:
        env["ANTHROPIC_MODEL"] = provider.model
        env["ANTHROPIC_SMALL_FAST_MODEL"] = provider.model
    else:
        print("\n⚠️  No model selected! Please open http://127.0.0.1:2424/admin and select a model first.\n")
        return 1
    # Some Claude Code builds/checks use alternate base-url variable names.
    env["ANTHROPIC_API_URL"] = base
    env["CLAUDE_CODE_API_BASE_URL"] = base
    try:
        p = subprocess.run([exe, *(argv if argv is not None else sys.argv[1:])], env=env)
        return p.returncode
    except FileNotFoundError:
        print(f"Could not find Claude Code binary '{claude}'. Install Claude Code or set CLAUDE_BINARY in {env_path()}.", file=sys.stderr)
        return 127


def main_server():
    raise SystemExit(cmd_server())


def main_claude():
    raise SystemExit(cmd_claude())
