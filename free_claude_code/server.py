from __future__ import annotations

import collections
import html
import json
import sys
import time
import socket
import uuid
import httpx
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional
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
LAST_LATENCY: Dict[str, float] = {"value": 0.0}

# Global HTTPX client for connection pooling and HTTP/2 support.
# Max 20 connections, keepalive 30s.
HTTP_CLIENT = httpx.Client(
    http2=True,
    timeout=httpx.Timeout(300.0, connect=60.0),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)

# Model list cache
MODEL_CACHE: Dict[str, Any] = {
    "items": [],
    "expires_at": 0,
}
MODEL_CACHE_TTL = 3600  # 1 hour

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
    headers: Dict[str, str] = {}
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


def call_openai_compatible(provider, body: Dict[str, Any]):
    validate_provider_ready(provider)
    url = provider.base_url.rstrip("/") + "/chat/completions"

    if body.get("stream"):
        return HTTP_CLIENT.stream("POST", url, json=body, headers=provider_headers(provider))
    else:
        return HTTP_CLIENT.post(url, json=body, headers=provider_headers(provider))


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
    resp = HTTP_CLIENT.get(url, headers=headers or {}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def list_provider_models(provider) -> tuple[list[str], str]:
    """Return NVIDIA model ids.

    First use NVIDIA's native OpenAI-compatible /models endpoint with the user's
    API key. Then merge NVIDIA's public featured catalog so the selector shows a
    broader NVIDIA catalog instead of only a tiny subset. Claude/Anthropic ids
    are filtered later.
    """
    validate_provider_ready(provider)
    ids: list[str] = []
    sources: list[str] = []

    # Native authenticated NVIDIA API list.
    data = fetch_json(provider.base_url.rstrip("/") + "/models", provider_headers(provider, content_type=False), 30)
    for mid in extract_model_ids(data):
        _add_model_id(ids, mid)
    sources.append(f"native /models: {len(ids)}")

    # Public NVIDIA catalog feed used only to add missing NVIDIA catalog entries.
    try:
        before = len(ids)
        catalog = fetch_json(NVIDIA_FEATURED_MODELS_URL, {}, 15)
        for mid in extract_model_ids(catalog):
            _add_model_id(ids, mid)
        sources.append(f"ngc catalog +{len(ids) - before}")
    except Exception as e:
        sources.append(f"ngc catalog unavailable: {e}")

    return ids, ", ".join(sources)


def models_response(provider, values: Dict[str, str]) -> Dict[str, Any]:
    global MODEL_CACHE
    now = time.time()

    # Return cached models if valid
    if MODEL_CACHE["items"] and MODEL_CACHE["expires_at"] > now:
        sys.stderr.write(f"[models] returning {len(MODEL_CACHE['items'])} cached NVIDIA models\n")
        return _format_models_response(MODEL_CACHE["items"], provider.model)

    source = "nvidia-api"
    try:
        # Preferred path: show ALL model ids returned by NVIDIA's native /models
        # endpoint for this key, plus NVIDIA's public catalog entries.
        ordered, source = list_provider_models(provider)

        # Update cache
        MODEL_CACHE["items"] = ordered
        MODEL_CACHE["expires_at"] = now + MODEL_CACHE_TTL
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
    return _format_models_response(ordered, provider.model, source)


def _format_models_response(ordered: list[str], selected_model: str, source: Optional[str] = None) -> Dict[str, Any]:
    # Last safety filter: never return Anthropic/Claude ids from this proxy.
    ordered = [m for m in ordered if m and not m.startswith("claude-") and "anthropic" not in m.lower()]

    # Ensure the selected model is at the top of the list.
    if selected_model in ordered:
        ordered.remove(selected_model)
        ordered.insert(0, selected_model)
    elif selected_model:
        ordered.insert(0, selected_model)

    if source:
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
        "nim-proxy",
        values.get("ANTHROPIC_MODEL", "free-claude-code"),
        values.get("ANTHROPIC_SMALL_FAST_MODEL", "free-claude-code"),
    }
    # If Claude Code sends a built-in Anthropic model name, map it to the
    # configured upstream model. If the user selected a real /v1/models item,
    # use that upstream model id directly.
    if requested and requested not in aliases and not requested.startswith("claude-"):
        return requested
    return provider.model


class Handler(BaseHTTPRequestHandler):
    server_version = "FreeClaudeCode/1.1"

    def log_message(self, fmt, *args):
        msg = "[%s] %s" % (self.log_date_time_string(), fmt % args)
        sys.stderr.write(msg + "\n")
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
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            values = load_env()
            provider = get_provider(values)
            return self._send(200, {"ok": True, "name": "free-claude-code", "provider": provider.name, "model": provider.model})
        if path in ("/v1/models", "/models"):
            # Check for no-cache header to force refresh
            cache_control = self.headers.get("Cache-Control", "")
            if "no-cache" in cache_control:
                global MODEL_CACHE
                MODEL_CACHE["expires_at"] = 0

            values = load_env()
            provider = get_provider(values)
            try:
                return self._send(200, models_response(provider, values), {"Cache-Control": "no-store, no-cache, must-revalidate"})
            except Exception as e:
                return self._send(500, {"type": "error", "error": {"type": "models_error", "message": str(e)}})
        if path == "/admin":
            return self._admin_get()
        if path == "/admin/logs":
            return self._send(200, {"logs": list(LOG_QUEUE), "latency": LAST_LATENCY.get("value", 0.0)})
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
        if path == "/admin":
            return self._admin_post()
        if path == "/admin/test":
            return self._admin_test()
        return self._send(404, {"type": "error", "error": {"type": "not_found", "message": path}})

    def _messages(self):
        start_time = time.time()
        upstream_model = "unknown"
        try:
            values = load_env()
            provider = get_provider(values)
            body = self._read_json()
            max_tokens = int(values.get("DEFAULT_MAX_TOKENS", "4096") or "4096")
            upstream_model = selected_upstream_model(body, provider, values)
            upstream = build_openai_request(body, upstream_model, max_tokens)

            if body.get("stream"):
                with call_openai_compatible(provider, upstream) as resp:
                    resp.raise_for_status()
                    self._pipe_stream(resp, body.get("model") or values.get("ANTHROPIC_MODEL", "free-claude-code"), start_time)
                return

            resp = call_openai_compatible(provider, upstream)
            resp.raise_for_status()
            data = resp.json()

            latency = time.time() - start_time
            LAST_LATENCY["value"] = latency
            self.log_message("Request completed in %.2fs", latency)

            return self._send(200, openai_to_anthropic(data, body.get("model") or values.get("ANTHROPIC_MODEL", "free-claude-code")))
        except httpx.HTTPStatusError as e:
            detail = e.response.text
            try:
                # Try to extract a cleaner message from JSON if possible
                err_obj = e.response.json()
                if "detail" in err_obj:
                    detail = err_obj["detail"]
                elif "error" in err_obj and "message" in err_obj["error"]:
                    detail = err_obj["error"]["message"]
            except:
                pass
            code = e.response.status_code
            msg = f"NVIDIA NIM Error ({code}): {detail}"
            if code == 401:
                msg = "NVIDIA NIM API Key is invalid or expired (401 Unauthorized). Please check your settings in the Admin UI."
            elif code == 404:
                msg = f"Model '{upstream_model}' not found or not accessible with your API key (404 Not Found)."
            return self._send(code, {"type": "error", "error": {"type": "upstream_error", "message": msg[:4000]}})
        except Exception as e:
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

    def _pipe_stream(self, resp, request_model: str, start_time: float):
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
        tool_calls: Dict[int, Dict[str, str]] = {}
        first_byte = True

        for line in resp.iter_lines():
            try:
                if not line or not line.startswith("data:"):
                    continue
                if first_byte:
                    self.log_message("First stream byte received in %.2fs", time.time() - start_time)
                    first_byte = False

                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue

                obj = json.loads(data)
                choice = (obj.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if choice.get("finish_reason"):
                    finish = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"
                text = delta.get("content")
                if text:
                    if not text_started:
                        text_started = True
                        self._sse("content_block_start", {"type": "content_block_start", "index": text_index, "content_block": {"type": "text", "text": ""}})
                    self._sse("content_block_delta", {"type": "content_block_delta", "index": text_index, "delta": {"type": "text_delta", "text": text}})
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index", len(tool_calls)))
                    cur = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        cur["id"] = tc.get("id")
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        cur["name"] += fn.get("name")
                    if fn.get("arguments"):
                        cur["args"] += fn.get("arguments")
                    finish = "tool_use"
            except BrokenPipeError:
                return
            except Exception:
                continue
        block_index = 0
        if text_started:
            self._sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
            block_index = 1
        for tc in [tool_calls[k] for k in sorted(tool_calls)]:
            tool_id = tc.get("id") or "toolu_" + uuid.uuid4().hex
            self._sse("content_block_start", {"type": "content_block_start", "index": block_index, "content_block": {"type": "tool_use", "id": tool_id, "name": tc.get("name") or "tool", "input": {}}})
            if tc.get("args"):
                self._sse("content_block_delta", {"type": "content_block_delta", "index": block_index, "delta": {"type": "input_json_delta", "partial_json": tc.get("args")}})
            self._sse("content_block_stop", {"type": "content_block_stop", "index": block_index})
            block_index += 1
        if not text_started and not tool_calls:
            self._sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self._sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": finish, "stop_sequence": None}, "usage": {"output_tokens": 0}})
        self._sse("message_stop", {"type": "message_stop"})

        latency = time.time() - start_time
        LAST_LATENCY["value"] = latency
        self.log_message("Stream completed in %.2fs", latency)

        self.close_connection = True

    def _is_loopback(self) -> bool:
        host = self.client_address[0]
        return host in ("127.0.0.1", "::1", "localhost")

    def _admin_get(self):
        if not self._is_loopback():
            return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        values = load_env()
        provider = get_provider(values)
        api_value = provider.api_key or ""
        current_model = provider.model
        last_model = values.get("LAST_MODEL", "")

        models = []
        try:
            if api_value and api_value != "your-api-key":
                models, _ = list_provider_models(provider)
        except Exception:
            pass

        if not models:
            models = FALLBACK_NVIDIA_NIM_MODELS
            if current_model and current_model not in models:
                models = [current_model] + models

        options = "".join(f'<option value="{html.escape(m)}"{ " selected" if m == current_model else ""}>{html.escape(m)}</option>' for m in models)

        latency_val = LAST_LATENCY.get("value", 0.0)
        latency_html = f"<p>Last request latency: <strong id='latencyVal'>{latency_val:.2f}s</strong></p>" if latency_val > 0 else "<p>Last request latency: <strong id='latencyVal'>N/A</strong></p>"

        last_model_html = ""
        if last_model and last_model != current_model:
            last_model_html = f"<h3>Last Used Model</h3><div style='margin-bottom:1rem;'><button type='button' style='padding:0.4rem 0.8rem;font-size:0.8rem;' onclick='document.getElementsByName(\"NVIDIA_NIM_MODEL\")[0].value=\"{html.escape(last_model)}\"'>{html.escape(last_model)}</button></div>"

        html_doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>My ClaudeCode Server Admin</title>
<style>
  :root {{ --bg: #fff; --text: #333; --border: #ddd; --section: #f9f9f9; --btn: #007bff; --btn-text: #fff; --code-bg: #eee; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #1e1e1e; --text: #e0e0e0; --border: #444; --section: #2d2d2d; --btn: #375a7f; --btn-text: #fff; --code-bg: #333; }}
  }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2rem auto; max-width: 800px; line-height: 1.5; background: var(--bg); color: var(--text); padding: 0 1rem; }}
  input, select {{ width: 100%; padding: .7rem; margin: .25rem 0 1.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--text); box-sizing: border-box; }}
  section {{ border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin: 1.5rem 0; background: var(--section); }}
  button {{ padding: .8rem 1.2rem; border: none; border-radius: 6px; background: var(--btn); color: var(--btn-text); cursor: pointer; font-weight: 600; }}
  button:hover {{ opacity: 0.9; }}
  button.secondary {{ background: #6c757d; margin-left: 0.5rem; }}
  code {{ background: var(--code-bg); padding: .2rem .4rem; border-radius: 4px; }}
  h1, h2, h3 {{ margin-top: 0; }}
  .logs {{ background: #000; color: #00ff00; padding: 1rem; border-radius: 6px; font-family: monospace; height: 200px; overflow-y: auto; font-size: 0.85rem; border: 1px solid #444; }}
  .status {{ margin-top: 1rem; font-weight: bold; padding: 0.5rem; border-radius: 4px; display: none; }}
  .status.success {{ background: #28a745; color: #fff; display: block; }}
  .status.error {{ background: #dc3545; color: #fff; display: block; }}
</style></head><body>
<h1>My ClaudeCode Admin Panel</h1>
<p>NVIDIA NIM proxy configuration and monitoring.</p>

<section>
  <h3>Performance Status</h3>
  {latency_html}
  <p>HTTP/2 Support: <strong>Enabled</strong></p>
  <p>Connection Pooling: <strong>Active</strong></p>
  <button type="button" class="secondary" style="margin-left:0;" onclick="refreshModels()">Refresh Model List</button>
</section>

<form id="configForm" method="post">
<section>
  <h3>NVIDIA NIM Settings</h3>
  <label>NVIDIA_NIM_API<input name="NVIDIA_NIM_API" value="{html.escape(mask(api_value))}" placeholder="your-api-key"></label>
  <label>Default Model (NVIDIA_NIM_MODEL)<br><select name="NVIDIA_NIM_MODEL">{options}</select></label>
  {last_model_html}
  <div style="display:flex;">
    <button type="submit">Save Settings</button>
    <button type="button" class="secondary" onclick="testConnection()">Test Connection</button>
  </div>
  <div id="testStatus" class="status"></div>
</section>
</form>

<section>
  <h3>Live Activity Logs</h3>
  <div id="logViewer" class="logs">Loading logs...</div>
</section>

<section>
  <h3>System Info</h3>
  <p>Server URL: <code>http://{html.escape(values.get('HOST', DEFAULT_HOST))}:{html.escape(values.get('PORT', DEFAULT_PORT))}</code></p>
  <p>Models endpoint: <code>/v1/models</code> (shows NVIDIA NIM model ids only)</p>
</section>

<script>
async function testConnection() {{
  const status = document.getElementById('testStatus');
  status.className = 'status';
  status.textContent = 'Testing connection...';
  status.style.display = 'block';

  const form = document.getElementById('configForm');
  const formData = new FormData(form);
  const data = {{}};
  formData.forEach((value, key) => data[key] = value);

  try {{
    const resp = await fetch('/admin/test', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(data)
    }});
    const result = await resp.json();
    if (result.ok) {{
      status.className = 'status success';
      status.textContent = '✅ Success: Connection verified and model is accessible.';
    }} else {{
      status.className = 'status error';
      status.textContent = '❌ Error: ' + result.message;
    }}
  }} catch (e) {{
    status.className = 'status error';
    status.textContent = '❌ Error: ' + e.message;
  }}
}}

async function refreshModels() {{
  const btn = event.target;
  const oldText = btn.textContent;
  btn.textContent = 'Refreshing...';
  btn.disabled = true;
  try {{
    await fetch('/v1/models', {{ headers: {{ 'Cache-Control': 'no-cache' }} }});
    location.reload();
  }} catch (e) {{
    alert('Failed to refresh models: ' + e.message);
  }} finally {{
    btn.textContent = oldText;
    btn.disabled = false;
  }}
}}

async function updateLogs() {{
  try {{
    const resp = await fetch('/admin/logs');
    const data = await resp.json();

    const viewer = document.getElementById('logViewer');
    const atBottom = viewer.scrollHeight - viewer.scrollTop <= viewer.clientHeight + 10;
    viewer.textContent = data.logs.join('\\n');
    if (atBottom) viewer.scrollTop = viewer.scrollHeight;

    if (data.latency > 0) {{
      document.getElementById('latencyVal').textContent = data.latency.toFixed(2) + 's';
    }}
  }} catch (e) {{}}
}}

setInterval(updateLogs, 2000);
updateLogs();
</script>
</body></html>"""
        return self._send_text(200, html_doc)

    def _admin_test(self):
        if not self._is_loopback():
            return self._send(403, {"ok": False, "message": "Admin UI is only available from localhost"})
        try:
            data = self._read_json()
            values = load_env()
            api_key = data.get("NVIDIA_NIM_API", "")
            # If the value is masked, use the one from env.
            if "…" in api_key:
                api_key = get_provider(values).api_key

            model = data.get("NVIDIA_NIM_MODEL", values.get("NVIDIA_NIM_MODEL", DEFAULT_NVIDIA_NIM_MODEL))

            if not api_key or api_key == "your-api-key":
                return self._send(200, {"ok": False, "message": "API key is missing"})

            # Simple test: call /models
            url = f"{DEFAULT_NVIDIA_NIM_BASE_URL}/models"
            resp = HTTP_CLIENT.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            resp.raise_for_status()
            models_data = resp.json()
            available_models = extract_model_ids(models_data)
            if model in available_models:
                return self._send(200, {"ok": True})
            else:
                return self._send(200, {"ok": False, "message": f"Model '{model}' not found in your account's available models."})
        except httpx.HTTPStatusError as e:
            msg = e.response.text
            try:
                err_data = e.response.json()
                if "detail" in err_data: msg = err_data["detail"]
            except: pass
            return self._send(200, {"ok": False, "message": f"NVIDIA API Error: {msg}"})
        except Exception as e:
            return self._send(200, {"ok": False, "message": str(e)})

    def _admin_post(self):
        if not self._is_loopback():
            return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        n = int(self.headers.get("Content-Length", "0") or "0")
        form = parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        updates: Dict[str, str] = {}
        allowed = {"NVIDIA_NIM_API", "NVIDIA_NIM_MODEL"}
        for k, v in form.items():
            if k not in allowed:
                continue
            val = v[0].strip()
            # Keep old key if the user submitted the masked value.
            if k == "NVIDIA_NIM_API" and "…" in val:
                continue
            updates[k] = val

        # Track last used model
        if "NVIDIA_NIM_MODEL" in updates:
            values = load_env()
            old_model = values.get("NVIDIA_NIM_MODEL", "")
            if old_model and old_model != updates["NVIDIA_NIM_MODEL"]:
                updates["LAST_MODEL"] = old_model

        # Clear model cache on settings change
        global MODEL_CACHE
        MODEL_CACHE["expires_at"] = 0

        write_env_values(updates)
        self.send_response(303)
        self.send_header("Location", "/admin")
        self.end_headers()


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, socket.timeout)):
            return
        super().handle_error(request, client_address)


def run_server(host: str, port: int):
    httpd = QuietThreadingHTTPServer((host, port), Handler)
    return httpd
