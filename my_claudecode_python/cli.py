import argparse
import os
import sys
import uvicorn
from .server import run_server
from .config import DEFAULT_HOST, DEFAULT_PORT, write_env_values, load_env

def main_server():
    parser = argparse.ArgumentParser(description="My Free Agents Server")
    parser.add_argument("--host", default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    parser.add_argument("--set-key", help="Set NVIDIA NIM API key and exit")
    parser.add_argument("--admin-only", action="store_true", help="Run only the Admin UI")
    args = parser.parse_args()

    if args.set_key:
        write_env_values({"NVIDIA_NIM_API": args.set_key})
        print("API key saved.")
        return

    values = load_env()
    host = args.host or values.get("HOST", DEFAULT_HOST)
    port = args.port or int(values.get("PORT", DEFAULT_PORT))

    if args.admin_only:
        print(f"Starting My Free Agents Admin UI on http://{host}:{port}/admin")
        # In a real implementation, we would disable the proxy endpoints
    else:
        print(f"Starting My Free Agents Server on http://{host}:{port}")

    app = run_server(host, port)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass

def main_claude():
    values = load_env()
    host = values.get("HOST", DEFAULT_HOST)
    port = values.get("PORT", DEFAULT_PORT)

    os.environ["ANTHROPIC_BASE_URL"] = f"http://{host}:{port}"
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-free-agents-123"

    # Execute Claude Code
    import subprocess
    cmd = ["claude"] + sys.argv[1:]
    try:
        subprocess.run(cmd)
    except FileNotFoundError:
        print("Error: 'claude' command not found. Please install Claude Code CLI.")
        sys.exit(1)

if __name__ == "__main__":
    main_server()
