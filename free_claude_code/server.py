from __future__ import annotations

import collections
import html
import json
import sys
import time
import socket
import httpx
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional, List
from urllib.parse import parse_qs, urlparse

from .anthropic import build_openai_request, estimate_tokens, openai_to_anthropic
from .config import (
    DEFAULT_HOST,
    DEFAULT_NVIDIA_NIM_BASE_URL,
    DEFAULT_NVIDIA_NIM_MODEL,
    DEFAULT_PORT,
    get_provider,
    load_env,
    write_env_values,
)

SENSITIVE_KEYS = ("API", "API_KEY")

LOG_QUEUE: collections.deque[str] = collections.deque(maxlen=50)

# Cache for /v1/models to avoid slow network calls.
_MODELS_CACHE: Dict[str, Any] = {}
_MODELS_CACHE_TIME: float = 0
MODELS_CACHE_TTL = 3600  # 1 hour

# Used only if NVIDIA's /models endpoint is temporarily unavailable. The real
# /models response is preferred whenever the user's key can access it.
NVIDIA_FEATURED_MODELS_URL = "https://assets.ngc.nvidia.com/products/api-catalog/featured-models.json"

FALLBACK_NVIDIA_NIM_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nemotron-3-super-120b-a12b",
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.6",
    "minimaxai/minimax-m3",
    "meta/llama-3.1-70b-instruct",
    "meta/llama-3.1-8b-instruct",
    "meta/llama-3.3-70b-instruct",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "nvidia/nemotron-mini-4b-instruct",
    "nvidia/nemotron-4-340b-instruct",
    "mistralai/mistral-small-24b-instruct",
    "deepseek-ai/deepseek-v3.1",
]


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "********"
    return value[:6] + "…" + value[-4:]


class ProxyError(Exception):
    pass


def provider_headers(provider, content_type: bool = True) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": "NVIDIA-NIM-Proxy/1.1",
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    if provider.api_key:
        headers["Authorization"] = f"Bearer {provider.api_key}"
    return headers


def validate_provider_ready(provider):
    if not provider.base_url:
        raise ProxyError(f"{provider.name}_BASE_URL is empty")
    if provider.needs_key and (not provider.api_key or "your-key" in provider.api_key or provider.api_key == "your-api-key"):
        raise ProxyError("NVIDIA_NIM_API is missing or still a placeholder")


def call_openai_compatible(provider, body: Dict[str, Any], stream: bool = False):
    validate_provider_ready(provider)
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = provider_headers(provider)

    client = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))
    if stream:
        return client.stream("POST", url, json=body, headers=headers)
    else:
        return client.post(url, json=body, headers=headers)


def _looks_like_model_id(value: str) -> bool:
    value = value.strip()
    if not value or " " in value or len(value) > 160:
        return False
    if value.startswith("http://") or value.startswith("https://"):
        return False
    # NVIDIA model ids are usually provider/name or compact lowercase ids.
    return "/" in value or value.replace("-", "").replace("_", "").replace(".", "").isalnum()


def _add_model_id(ids: list[str], value: Any) -> None:
    if value is None:
        return
    mid = str(value).strip()
    if _looks_like_model_id(mid) and mid not in ids:
        ids.append(mid)


def extract_model_ids(data: Any) -> list[str]:
    """Extract model ids from OpenAI/NVIDIA/catalog shaped JSON.

    NVIDIA endpoints and public catalogs are not always shaped the same way, so
    this recursively extracts values from known id fields while avoiding display
    labels such as "model-name".
    """
    ids: list[str] = []

    def walk(obj: Any):
        if isinstance(obj, list):
            for x in obj:
                walk(x)
            return
        if isinstance(obj, dict):
            # Check for common ID keys first.
            for key in ("id", "model", "modelId", "model_id"):
                if key in obj and isinstance(obj[key], str):
                    _add_model_id(ids, obj.get(key))

            # Recurse into other keys, but avoid known display/label/metadata keys.
            for key, value in obj.items():
                if key in ("model-name", "display_name", "description", "owned_by", "object", "created", "created_at"):
                    continue
                if isinstance(value, (dict, list)):
                    walk(value)
            return

    walk(data)
    return ids


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Any:
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url, headers=headers or {})
        resp.raise_for_status()
        return resp.json()


def list_provider_models(provider) -> tuple[list[str], str]:
    """Return NVIDIA model ids.

    First use NVIDIA's native OpenAI-compatible /models endpoint with the user's
    API key. Then merge NVIDIA's public featured catalog so the selector shows a
    broader NVIDIA catalog instead of only a tiny subset. Claude/Anthropic ids
    are filtered later.
    """
    global _MODELS_CACHE_TIME, _MODELS_CACHE
    now = time.time()
    cache_key = f"{provider.base_url}:{provider.api_key}"
    if _MODELS_CACHE and cache_key in _MODELS_CACHE and (now - _MODELS_CACHE_TIME) < MODELS_CACHE_TTL:
        return _MODELS_CACHE[cache_key]

    validate_provider_ready(provider)
    ids: list[str] = []
    sources: list[str] = []

    # Native authenticated NVIDIA API list.
    try:
        data = fetch_json(provider.base_url.rstrip("/") + "/models", provider_headers(provider, content_type=False), 10)
        for mid in extract_model_ids(data):
            _add_model_id(ids, mid)
        sources.append(f"native /models: {len(ids)}")
    except Exception as e:
        sources.append(f"native /models unavailable: {e}")

    # Public NVIDIA catalog feed used only to add missing NVIDIA catalog entries.
    try:
        before = len(ids)
        catalog = fetch_json(NVIDIA_FEATURED_MODELS_URL, {}, 5)
        for mid in extract_model_ids(catalog):
            _add_model_id(ids, mid)
        sources.append(f"ngc catalog +{len(ids) - before}")
    except Exception as e:
        sources.append(f"ngc catalog unavailable: {e}")

    res = (ids, ", ".join(sources))
    if ids:
        _MODELS_CACHE[cache_key] = res
        _MODELS_CACHE_TIME = now
    return res


def models_response(provider, values: Dict[str, str]) -> Dict[str, Any]:
    source = "nvidia-api"
    try:
        # Preferred path: show ALL model ids returned by NVIDIA's native /models
        # endpoint for this key, plus NVIDIA's public catalog entries.
        ordered, source = list_provider_models(provider)
    except Exception as e:
        # Fallback path: still never show Anthropic models. This prevents Claude
        # Code from falling back to its built-in Anthropic list when NVIDIA's
        # /models endpoint is temporarily unavailable or the key is not set yet.
        source = f"fallback: {e}"
        ordered = []
        if provider.model:
            ordered.append(provider.model)
        for mid in FALLBACK_NVIDIA_NIM_MODELS:
            if mid not in ordered:
                ordered.append(mid)
    # Ensure ordered is a list
    ordered = list(ordered)
    # Last safety filter: never return Anthropic/Claude ids from this proxy.
    ordered = [m for m in ordered if m and not m.startswith("claude-") and "anthropic" not in m.lower()]

    # Ensure the selected model is at the top of the list.
    if provider.model in ordered:
        ordered.remove(provider.model)
        ordered.insert(0, provider.model)
    elif provider.model:
        ordered.insert(0, provider.model)

    sys.stderr.write(f"[models] returning {len(ordered)} NVIDIA models from {source}\n")
    items = [{
        "id": mid,
        "type": "model",
        "display_name": mid,
        "created_at": "2024-01-01T00:00:00Z",
        "owned_by": "nvidia-nim",
    } for mid in ordered]
    return {
        "object": "list",
        "data": items,
        "has_more": False,
        "first_id": items[0]["id"] if items else None,
        "last_id": items[-1]["id"] if items else None,
    }


def selected_upstream_model(body: Dict[str, Any], provider, values: Dict[str, str]) -> str:
    requested = str(body.get("model") or "").strip()
    aliases = {
        "",
        "free-claude-code",
        "my-free-agents",
        "nim-proxy",
        values.get("ANTHROPIC_MODEL", "my-free-agents"),
        values.get("ANTHROPIC_SMALL_FAST_MODEL", "my-free-agents"),
    }
    # If Claude Code sends a built-in Anthropic model name, map it to the
    # configured upstream model. If the user selected a real /v1/models item,
    # use that upstream model id directly.
    if requested and requested not in aliases and not requested.startswith("claude-"):
        return requested
    return provider.model


class Handler(BaseHTTPRequestHandler):
    server_version = "MyFreeAgents/1.1"

    def log_message(self, fmt, *args):
        msg = "[%s] %s" % (self.log_date_time_string(), fmt % args)
        if "HEAD" not in msg: # Keep logs cleaner
            sys.stderr.write(msg + "\n")
            sys.stderr.flush()
        LOG_QUEUE.append(msg)

    def _send(self, status: int, data: Any, headers: Optional[Dict[str, str]] = None):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True

    def _send_text(self, status: int, text: str, content_type: str = "text/html; charset=utf-8"):
        raw = text.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True

    def _read_json(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n > 25_000_000:
            raise ProxyError("Request body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS,HEAD")
        self.send_header("Access-Control-Allow-Headers", "content-type,authorization,anthropic-version,anthropic-beta,x-api-key")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            values = load_env()
            provider = get_provider(values)
            return self._send(200, {"ok": True, "name": "my-free-agents", "provider": provider.name, "model": provider.model})
        if path in ("/v1/auth/status", "/v1/identify", "/v1/users/current"):
            return self._send(200, {
                "id": "user_local_proxy",
                "email": "proxy@localhost",
                "account": {"id": "acc_local", "name": "Local Proxy User"},
                "logged_in": True
            })
        if path in ("/v1/models", "/models"):
            values = load_env()
            provider = get_provider(values)
            try:
                return self._send(200, models_response(provider, values), {"Cache-Control": "no-store, no-cache, must-revalidate"})
            except Exception as e:
                return self._send(500, {"type": "error", "error": {"type": "models_error", "message": str(e)}})
        if path == "/admin":
            return self._admin_get()
        if path == "/admin/logs":
            return self._send(200, {"logs": list(LOG_QUEUE)})
        if path == "/admin/logs/export":
            log_text = "\n".join(list(LOG_QUEUE))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Disposition", "attachment; filename=claude-nim-proxy.log")
            self.send_header("Content-Length", str(len(log_text)))
            self.end_headers()
            self.wfile.write(log_text.encode("utf-8"))
            return
        if path == "/admin/version":
            try:
                with httpx.Client(timeout=2) as client:
                    r = client.get("https://api.github.com/repos/Chintanpatel24/my-free-agents/releases/latest", headers={"User-Agent": "Claude-NIM-Proxy"})
                    data = r.json()
                    return self._send(200, {"latest": data.get("tag_name", "unknown")})
            except:
                return self._send(200, {"latest": "unknown"})
        if path == "/admin/current-model":
            values = load_env()
            return self._send(200, {"model": values.get("NVIDIA_NIM_MODEL", "")})
        return self._send(404, {"type": "error", "error": {"type": "not_found", "message": path}})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/v1/messages/count_tokens":
            try:
                body = self._read_json()
                return self._send(200, {"input_tokens": estimate_tokens({"messages": body.get("messages"), "system": body.get("system")})})
            except Exception as e:
                return self._send(400, {"type": "error", "error": {"type": "bad_request", "message": str(e)}})
        if path == "/v1/messages":
            return self._messages()
        if path in ("/v1/auth/status", "/v1/identify", "/v1/users/current"):
            return self._send(200, {
                "id": "user_local_proxy",
                "email": "proxy@localhost",
                "account": {"id": "acc_local", "name": "Local Proxy User"},
                "logged_in": True
            })
        if path == "/admin":
            return self._admin_post()
        if path == "/admin/test":
            # Start background model fetch if not already in cache
            import threading
            threading.Thread(target=self._background_fetch_models, daemon=True).start()
            return self._admin_test()
        if path == "/admin/launch":
            return self._send(200, {"ok": True, "command": "my-claudecode"})

        # If no POST route matches, check if it's a GET route that was sent as POST
        # some clients might do this incorrectly.
        return self._send(404, {"type": "error", "error": {"type": "not_found", "message": f"Path not found or method not allowed: {self.command} {path}"}})

    def _messages(self):
        start_time = time.time()
        try:
            sys.stderr.write(f"\n[Request] POST /v1/messages\n")
            values = load_env()
            provider = get_provider(values)
            if not provider.model:
                return self._send(400, {"type": "error", "error": {"type": "bad_request", "message": "No model selected. Please visit the admin panel at /admin and select an NVIDIA NIM model first."}})

            body = self._read_json()
            upstream_model = selected_upstream_model(body, provider, values)

            # Log the request details locally
            msgs = body.get("messages", [])
            last_msg = msgs[-1].get("content", "") if msgs else ""
            if isinstance(last_msg, list):
                last_msg = str(last_msg[0].get("text", "")) if last_msg else ""
            sys.stderr.write(f"  Model: {upstream_model}\n")
            sys.stderr.write(f"  Stream: {bool(body.get('stream'))}\n")
            sys.stderr.write(f"  User: {last_msg[:100]}{'...' if len(str(last_msg)) > 100 else ''}\n")
            sys.stderr.flush()

            max_tokens = int(values.get("DEFAULT_MAX_TOKENS", "4096") or "4096")
            upstream = build_openai_request(body, upstream_model, max_tokens)

            is_stream = bool(body.get("stream"))
            if is_stream:
                resp_ctx = call_openai_compatible(provider, upstream, stream=True)
                with resp_ctx as resp:
                    resp.raise_for_status()
                    res = self._pipe_stream(resp, body.get("model") or values.get("ANTHROPIC_MODEL", "my-free-agents"), start_time, upstream_model)
                    sys.stderr.write(f"  [Response] Stream finished in {time.time() - start_time:.2f}s\n")
                    sys.stderr.flush()
                    return res
            else:
                resp = call_openai_compatible(provider, upstream, stream=False)
                resp.raise_for_status()
                data = resp.json()
                anthropic_resp = openai_to_anthropic(data, body.get("model") or values.get("ANTHROPIC_MODEL", "my-free-agents"))
                sys.stderr.write(f"  [Response] OK in {time.time() - start_time:.2f}s\n")
                sys.stderr.flush()
                return self._send(200, anthropic_resp)

        except httpx.HTTPStatusError as e:
            detail = e.response.text
            try:
                err_obj = json.loads(detail)
                if "detail" in err_obj: detail = err_obj["detail"]
                elif "error" in err_obj and "message" in err_obj["error"]: detail = err_obj["error"]["message"]
            except: pass
            msg = f"NVIDIA NIM Error ({e.response.status_code}): {detail}"
            return self._send(e.response.status_code, {"type": "error", "error": {"type": "upstream_error", "message": msg[:4000]}})
        except Exception as e:
            sys.stderr.write(f"  [Error] {str(e)}\n")
            sys.stderr.flush()
            return self._send(500, {"type": "error", "error": {"type": "proxy_error", "message": str(e)}})

    def _sse(self, event: str, data: Dict[str, Any]) -> bool:
        try:
            self.wfile.write(f"event: {event}\n".encode())
            self.wfile.write(("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
            return False

    def _pipe_stream(self, resp, request_model: str, start_time: float, upstream_model: str):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
            return
        mid = "msg_" + uuid.uuid4().hex
        if not self._sse("message_start", {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": request_model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}):
            return
        finish = "end_turn"
        text_started = False
        text_index = 0
        tool_started: Dict[int, bool] = {}
        tool_ids: Dict[int, str] = {}

        for line in resp.iter_lines():
            try:
                if not line or not line.startswith("data:"): continue
                data = line[5:].strip()
                if not data or data == "[DONE]": continue
                obj = json.loads(data)
                choice = (obj.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}

                if choice.get("finish_reason"):
                    finish = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"

                # Handle Text
                text = delta.get("content")
                if text:
                    if not text_started:
                        text_started = True
                        self._sse("content_block_start", {"type": "content_block_start", "index": text_index, "content_block": {"type": "text", "text": ""}})
                    self._sse("content_block_delta", {"type": "content_block_delta", "index": text_index, "delta": {"type": "text_delta", "text": text}})

                # Handle Tool Calls (Immediate Streaming)
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", 0))

                    # In Anthropic, each tool call is a separate content block.
                    # We map OpenAI tool index to Anthropic content block index.
                    # Usually, index 0 is text (if present).
                    anthropic_idx = idx + (1 if text_started else 0)

                    if idx not in tool_started:
                        tool_started[idx] = True
                        tool_id = tc.get("id") or "toolu_" + uuid.uuid4().hex
                        tool_ids[idx] = tool_id
                        name = tc.get("function", {}).get("name") or "tool"
                        self._sse("content_block_start", {"type": "content_block_start", "index": anthropic_idx, "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}}})

                    args = tc.get("function", {}).get("arguments")
                    if args:
                        self._sse("content_block_delta", {"type": "content_block_delta", "index": anthropic_idx, "delta": {"type": "input_json_delta", "partial_json": args}})

                    finish = "tool_use"
            except BrokenPipeError: return
            except Exception: continue

        # Stop all blocks
        if text_started:
            self._sse("content_block_stop", {"type": "content_block_stop", "index": text_index})

        for idx in sorted(tool_started.keys()):
            anthropic_idx = idx + (1 if text_started else 0)
            self._sse("content_block_stop", {"type": "content_block_stop", "index": anthropic_idx})

        if not text_started and not tool_started:
            self._sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})

        self._sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": finish, "stop_sequence": None}, "usage": {"output_tokens": 0}})
        self._sse("message_stop", {"type": "message_stop"})
        self.close_connection = True

    def _is_loopback(self) -> bool:
        host = self.client_address[0]
        return host in ("127.0.0.1", "::1", "localhost")

    def _admin_get(self):
        if not self._is_loopback(): return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        values = load_env()
        provider = get_provider(values)
        api_value = provider.api_key or ""
        current_model = provider.model
        models = []
        try:
            if api_value and api_value != "your-api-key": models, _ = list_provider_models(provider)
        except Exception: pass
        if not models:
            models = FALLBACK_NVIDIA_NIM_MODELS
            if current_model and current_model not in models: models = [current_model] + models
        options = "".join(f'<option value="{html.escape(m)}"{ " selected" if m == current_model else ""}>{html.escape(m)}</option>' for m in models)

        html_doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>My ClaudeCode Server Admin</title>
<style>
  :root {{ --bg: #fff; --text: #333; --border: #ddd; --section: #f9f9f9; --btn: #007bff; --btn-text: #fff; --code-bg: #eee; --sidebar-bg: #f1f1f1; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #1e1e1e; --text: #e0e0e0; --border: #444; --section: #2d2d2d; --btn: #375a7f; --btn-text: #fff; --code-bg: #333; --sidebar-bg: #252525; }} }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; display: flex; height: 100vh; background: var(--bg); color: var(--text); }}
  .sidebar {{ width: 200px; background: var(--sidebar-bg); border-right: 1px solid var(--border); display: flex; flex-direction: column; padding: 1rem; }}
  .sidebar a {{ color: var(--text); text-decoration: none; padding: .75rem 1rem; border-radius: 6px; margin-bottom: .5rem; font-weight: 600; cursor: pointer; }}
  .sidebar a:hover {{ background: var(--section); }}
  .sidebar a.active {{ background: var(--btn); color: var(--btn-text); }}
  .content {{ flex: 1; padding: 2rem; overflow-y: auto; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  input, select {{ width: 100%; padding: .7rem; margin: .25rem 0 1.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); box-sizing: border-box; }}
  section {{ border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin: 1.5rem 0; background: var(--section); }}
  button {{ padding: .8rem 1.2rem; border: none; border-radius: 6px; background: var(--btn); color: var(--btn-text); cursor: pointer; font-weight: 600; }}
  button:hover {{ opacity: 0.9; }}
  button.secondary {{ background: #6c757d; margin-left: 0.5rem; }}
  code {{ background: var(--code-bg); padding: .2rem .4rem; border-radius: 4px; }}
  h1, h2, h3 {{ margin-top: 0; }}
  .page {{ display: none; }}
  .page.active {{ display: block; }}
  .logs {{ background: #000; color: #00ff00; padding: 1rem; border-radius: 6px; font-family: monospace; height: 300px; overflow-y: auto; font-size: 0.85rem; border: 1px solid #444; }}
  .status {{ margin-top: 1rem; font-weight: bold; padding: 0.5rem; border-radius: 4px; display: none; }}
  .status.success {{ background: #28a745; color: #fff; display: block; }}
  .status.error {{ background: #dc3545; color: #fff; display: block; }}
</style></head><body>
<div class="sidebar">
  <h2 style="font-size: 1.2rem; margin-bottom: 1.5rem;">Claude NIM Proxy</h2>
  <a onclick="showPage('config')" id="nav-config" class="active">Configuration</a>
  <div style="margin-top:auto; padding-top:1rem; border-top:1px solid var(--border);">
    <button onclick="launchClaude()" style="width:100%; font-size:0.8rem; padding:0.5rem;">Launch Claude</button>
  </div>
</div>
<div class="content">
  <div class="container">
    <div id="config-page" class="page active">
      <h1>Configuration</h1>
      <div id="updateBanner" style="display:none; background: #fff3cd; color: #856404; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #ffeeba;">New version available! Latest: <span id="latestVersion"></span>. Update using the script in README.</div>
      <p>NVIDIA NIM proxy settings.</p>
      <form id="configForm" method="post">
        <section>
          <h3>NVIDIA NIM Settings</h3>
          <label>NVIDIA_NIM_API<input name="NVIDIA_NIM_API" value="{html.escape(mask(api_value))}" placeholder="your-api-key"></label>
          <label>Default Model (NVIDIA_NIM_MODEL)<br><select id="modelSelect" name="NVIDIA_NIM_MODEL">{options}</select></label>
          <div style="display:flex;">
            <button type="submit">Save Settings</button>
            <button type="button" class="secondary" onclick="testConnection()">Verify & Fetch Models</button>
          </div>
          <div id="testStatus" class="status"></div>
        </section>
      </form>
      <section><h3>System Info</h3><p>Server URL: <code>http://{html.escape(values.get('HOST', DEFAULT_HOST))}:{html.escape(values.get('PORT', DEFAULT_PORT))}</code></p></section>
    </div>
  </div>
</div>
<script>
function showPage(id) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
  document.getElementById(id + '-page').classList.add('active');
  document.getElementById('nav-' + id).classList.add('active');
}}
async function testConnection() {{
  const status = document.getElementById('testStatus');
  status.className = 'status'; status.textContent = 'Verifying and fetching models...'; status.style.display = 'block';
  const form = document.getElementById('configForm');
  const formData = new FormData(form);
  const data = {{}}; formData.forEach((value, key) => data[key] = value);
  try {{
    const resp = await fetch('/admin/test', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(data) }});
    const result = await resp.json();
    if (result.ok) {{
      status.className = 'status success'; status.textContent = '✅ Success: Connection verified.';
      if (result.models && result.models.length > 0) {{
        const select = document.getElementById('modelSelect');
        const current = select.value; select.innerHTML = '';
        if (!current) {{ const p = document.createElement('option'); p.value = ''; p.textContent = '-- Select a Model --'; p.disabled = true; p.selected = true; select.appendChild(p); }}
        result.models.forEach(m => {{ const opt = document.createElement('option'); opt.value = m; opt.textContent = m; if (m === current) opt.selected = true; select.appendChild(opt); }});
        status.textContent += ' ' + result.models.length + ' models updated in list.';
      }}
    }} else {{ status.className = 'status error'; status.textContent = '❌ Error: ' + result.message; }}
  }} catch (e) {{ status.className = 'status error'; status.textContent = '❌ Error: ' + e.message; }}
}}
async function checkVersion() {{
  try {{
    const resp = await fetch('/admin/version');
    const data = await resp.json();
    if (data.latest !== 'unknown') {{
      const banner = document.getElementById('updateBanner');
      document.getElementById('latestVersion').textContent = data.latest; banner.style.display = 'block';
    }}
  }} catch (e) {{}}
}}
async function launchClaude() {{
  const resp = await fetch('/admin/launch', {{ method: 'POST' }});
  const data = await resp.json(); alert('To start Claude with the proxy, run this command in your terminal:\\n\\n' + data.command);
}}
async function updateCurrentModel() {{
  try {{
    const resp = await fetch('/admin/current-model');
    const data = await resp.json();
    if (data.model) {{
        const select = document.getElementById('modelSelect');
        let found = false;
        for (let i = 0; i < select.options.length; i++) {{ if (select.options[i].value === data.model) {{ select.options[i].selected = true; found = true; break; }} }}
        if (!found) {{ const opt = document.createElement('option'); opt.value = data.model; opt.textContent = data.model + ' (Current)'; opt.selected = true; select.appendChild(opt); }}
    }}
  }} catch (e) {{}}
}}
checkVersion(); updateCurrentModel();
</script></body></html>"""
        return self._send_text(200, html_doc)

    def _background_fetch_models(self):
        try:
            values = load_env()
            provider = get_provider(values)
            if provider.api_key:
                list_provider_models(provider)
        except Exception:
            pass

    def _admin_test(self):
        if not self._is_loopback(): return self._send(403, {"ok": False, "message": "Admin UI is only available from localhost"})
        try:
            data = self._read_json()
            values = load_env()
            api_key = data.get("NVIDIA_NIM_API", "")
            if "…" in api_key: api_key = get_provider(values).api_key
            if not api_key or api_key == "your-api-key": return self._send(200, {"ok": False, "message": "API key is missing"})
            url = f"{DEFAULT_NVIDIA_NIM_BASE_URL}/models"
            with httpx.Client(timeout=10) as client:
                resp = client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                models_data = resp.json()
                available_models = extract_model_ids(models_data)
                available_models = [m for m in available_models if m and not m.startswith("claude-") and "anthropic" not in m.lower()]
                return self._send(200, {"ok": True, "models": available_models})
        except httpx.HTTPStatusError as e:
            msg = e.response.text
            try:
                err_data = json.loads(msg)
                if "detail" in err_data: msg = err_data["detail"]
            except: pass
            return self._send(200, {"ok": False, "message": f"NVIDIA API Error: {msg}"})
        except Exception as e: return self._send(200, {"ok": False, "message": str(e)})

    def _admin_post(self):
        if not self._is_loopback(): return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        n = int(self.headers.get("Content-Length", "0") or "0")
        form = parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        updates: Dict[str, str] = {}
        allowed = {"NVIDIA_NIM_API", "NVIDIA_NIM_MODEL"}
        for k, v in form.items():
            if k not in allowed: continue
            val = v[0].strip()
            if k == "NVIDIA_NIM_API" and "…" in val: continue
            updates[k] = val
        write_env_values(updates)
        self.send_response(303)
        self.send_header("Location", "/admin")
        self.end_headers()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, socket.timeout)): return
        super().handle_error(request, client_address)


def run_server(host: str, port: int):
    httpd = QuietThreadingHTTPServer((host, port), Handler)
    return httpd
