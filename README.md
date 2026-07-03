# my-free-claudecode

Python local proxy for using **Claude Code** with **NVIDIA NIM** through an Anthropic-compatible local server.

Only two commands are installed:

```bash
my-claudecode-server   # starts the proxy server
my-claudecode          # opens Claude Code through that server
```

Only NVIDIA NIM is supported. No other provider settings are included.

## Important behavior

- `/v1/models` and `/models` return **NVIDIA model ids only**.
- The proxy first calls NVIDIA's native OpenAI-compatible endpoint with your API key:

```text
https://integrate.api.nvidia.com/v1/models
```

- It then adds NVIDIA's public API-catalog feed so the selector is not limited to a tiny subset:

```text
https://assets.ngc.nvidia.com/products/api-catalog/featured-models.json
```

- If NVIDIA's endpoints are temporarily unavailable, the proxy still returns a NVIDIA fallback list — never Anthropic models.
- If Claude Code sends a selected NVIDIA NIM model id, the proxy forwards that exact model id to NVIDIA NIM.
- If Claude Code sends a built-in Anthropic model id like `claude-...`, the proxy maps it to the default NVIDIA NIM model so requests do not break.

> This is not affiliated with Anthropic or NVIDIA. For Claude Code agent workflows, choose a NVIDIA NIM model that supports OpenAI-compatible tool/function calling.

## Install on macOS/Linux

```bash
git clone <your-repo-url> my-free-claudecode
cd my-free-claudecode
bash install.sh
```

Installed commands:

```text
~/.local/bin/my-claudecode-server
~/.local/bin/my-claudecode
```

## Install on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Installed commands:

```text
%USERPROFILE%\.free-claude-code\bin\my-claudecode-server.cmd
%USERPROFILE%\.free-claude-code\bin\my-claudecode.cmd
```

## Configure

The `.env` is intentionally minimal. It contains only the NVIDIA NIM API key:

```env
# Managed by My ClaudeCode Server /admin.
# Paste your NVIDIA NIM key here. Nothing else is required.

NVIDIA_NIM_API=your-api-key
```

macOS/Linux:

```bash
nano ~/.free-claude-code/app/.env
```

Windows:

```powershell
notepad $env:USERPROFILE\.free-claude-code\app\.env
```

Or save the key from terminal:

```bash
my-claudecode-server --set-key nvapi-your-real-key
```

## Use

Terminal 1:

```bash
my-claudecode-server
```

Terminal 2:

```bash
my-claudecode
```

In Claude Code, run `/models`. It should show NVIDIA model ids from the NVIDIA API/catalog, not Anthropic/Claude models. If you still see Claude models, stop Claude Code completely, keep `my-claudecode-server` running, and launch Claude Code only with `my-claudecode` so the wrapper can force the local proxy and NIM model env vars.

## Manual checks

Health:

```bash
curl http://127.0.0.1:3456/health
```

NVIDIA NIM models shown to Claude Code:

```bash
curl http://127.0.0.1:3456/v1/models
```

Alternative models endpoint, in case a client calls `/models`:

```bash
curl http://127.0.0.1:3456/models
```

Message test:

```bash
curl -s http://127.0.0.1:3456/v1/messages \
  -H 'content-type: application/json' \
  -H 'anthropic-version: 2023-06-01' \
  -d '{
    "model":"meta/llama-3.1-70b-instruct",
    "max_tokens":256,
    "messages":[{"role":"user","content":"Say hello in one sentence."}]
  }'
```

## Optional advanced overrides

These are optional environment variables only; they are not written to `.env`:

```bash
export NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
export NVIDIA_NIM_MODEL=meta/llama-3.1-70b-instruct
export HOST=127.0.0.1
export PORT=3456
export CLAUDE_BINARY=claude
```

## Verify before publishing

```bash
bash scripts/verify.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

## Uninstall

macOS/Linux:

```bash
~/.free-claude-code/app/uninstall.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\.free-claude-code\app\uninstall.ps1
```
