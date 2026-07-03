from __future__ import annotations

import html
import json
import sys
import time
import socket
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qs, urlparse

from .anthropic import build_openai_request, estimate_tokens, openai_to_anthropic
from .config import DEFAULT_HOST, DEFAULT_NVIDIA_NIM_BASE_URL, DEFAULT_PORT, get_provider, load_env, write_env_values

SENSITIVE_KEYS = ("API", "API_KEY")

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
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=provider_headers(provider), method="POST")
    return urllib.request.urlopen(req, timeout=300)


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
            for key in ("id", "model", "modelId", "model_id"):
                if key in obj:
                    _add_model_id(ids, obj.get(key))
            for key, value in obj.items():
                if key in ("model-name", "display_name", "description"):
                    continue
                if isinstance(value, (dict, list)):
                    walk(value)
            return
        if isinstance(obj, str):
            _add_model_id(ids, obj)

    walk(data)
    return ids


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 30) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    # Last safety filter: never return Anthropic/Claude ids from this proxy.
    ordered = [m for m in ordered if m and not m.startswith("claude-") and "anthropic" not in m.lower()]

    # Ensure the default GLM model is at the top of the list.
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
    server_version = "FreeClaudeCode/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

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
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type,authorization,anthropic-version,anthropic-beta,x-api-key")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            values = load_env()
            provider = get_provider(values)
            return self._send(200, {"ok": True, "name": "free-claude-code", "provider": provider.name, "model": provider.model})
        if path in ("/v1/models", "/models"):
            values = load_env()
            provider = get_provider(values)
            try:
                return self._send(200, models_response(provider, values), {"Cache-Control": "no-store, no-cache, must-revalidate"})
            except Exception as e:
                return self._send(500, {"type": "error", "error": {"type": "models_error", "message": str(e)}})
        if path == "/admin":
            return self._admin_get()
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
        return self._send(404, {"type": "error", "error": {"type": "not_found", "message": path}})

    def _messages(self):
        try:
            values = load_env()
            provider = get_provider(values)
            body = self._read_json()
            max_tokens = int(values.get("DEFAULT_MAX_TOKENS", "4096") or "4096")
            upstream_model = selected_upstream_model(body, provider, values)
            upstream = build_openai_request(body, upstream_model, max_tokens)
            resp = call_openai_compatible(provider, upstream)
            if body.get("stream"):
                return self._pipe_stream(resp, body.get("model") or values.get("ANTHROPIC_MODEL", "free-claude-code"))
            data = json.loads(resp.read().decode("utf-8"))
            return self._send(200, openai_to_anthropic(data, body.get("model") or values.get("ANTHROPIC_MODEL", "free-claude-code")))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            return self._send(e.code, {"type": "error", "error": {"type": "upstream_error", "message": detail[:4000]}})
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

    def _pipe_stream(self, resp, request_model: str):
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
        buffer = ""
        finish = "end_turn"
        text_started = False
        text_index = 0
        tool_calls: Dict[int, Dict[str, str]] = {}
        for raw in resp:
            try:
                buffer += raw.decode("utf-8", "replace")
                while "\n\n" in buffer:
                    part, buffer = buffer.split("\n\n", 1)
                    line = next((x for x in part.splitlines() if x.startswith("data:")), "")
                    data = line[5:].strip() if line else ""
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
        self.close_connection = True

    def _is_loopback(self) -> bool:
        host = self.client_address[0]
        return host in ("127.0.0.1", "::1", "localhost")

    def _admin_get(self):
        if not self._is_loopback():
            return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        values = load_env()
        api_value = values.get('NVIDIA_NIM_API') or values.get('NVIDIA_NIM_API_KEY') or ''
        html_doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>My ClaudeCode Server Admin</title>
<style>body{{font-family:system-ui;margin:2rem;max-width:760px}}input{{width:100%;padding:.7rem;margin:.25rem 0 1rem}}section{{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}}button{{padding:.8rem 1.2rem}}code{{background:#eee;padding:.2rem}}</style></head><body>
<h1>My ClaudeCode Server /admin</h1><p>NVIDIA NIM-only settings. The .env file stores only <code>NVIDIA_NIM_API</code>. Models come from NVIDIA NIM <code>/v1/models</code>.</p>
<form method="post">
<section><h3>NVIDIA NIM</h3>
<label>NVIDIA_NIM_API<input name="NVIDIA_NIM_API" value="{html.escape(mask(api_value))}" placeholder="leave masked to keep existing key"></label>
</section>
<button type="submit">Save API key</button></form>
<p>Server URL: <code>http://{html.escape(values.get('HOST', DEFAULT_HOST))}:{html.escape(values.get('PORT', DEFAULT_PORT))}</code></p>
<p>Models endpoint: <code>/v1/models</code> shows NVIDIA NIM model ids only.</p></body></html>"""
        return self._send_text(200, html_doc)

    def _admin_post(self):
        if not self._is_loopback():
            return self._send_text(403, "Admin UI is only available from localhost", "text/plain")
        n = int(self.headers.get("Content-Length", "0") or "0")
        form = parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        updates: Dict[str, str] = {}
        allowed = {"NVIDIA_NIM_API"}
        for k, v in form.items():
            if k not in allowed:
                continue
            val = v[0].strip()
            # Keep old key if the user submitted the masked value.
            if k in ("NVIDIA_NIM_API", "NVIDIA_NIM_API_KEY") and "…" in val:
                continue
            updates[k] = val
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
