from __future__ import annotations

import collections
import html
import json
import sys
import time
import socket
import uuid
import httpx
from contextlib import contextmanager
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
LAST_FIRST_BYTE: Dict[str, float] = {"value": 0.0}

# Global HTTPX clients for connection pooling. NVIDIA's endpoint is fast over
# HTTP/1.1 and some local Python/http2 combinations stall for a long time, so
# HTTP/1.1 is the safe default. Set NVIDIA_NIM_HTTP2=1 to opt in.
CLIENT_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=10.0)
STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=10.0)
FAST_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=10.0, pool=5.0)
HTTP_CLIENTS: Dict[bool, Optional[httpx.Client]] = {False: None, True: None}
RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
RETRYABLE_EXC = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
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


def env_bool(values: Dict[str, str], key: str, default: bool = False) -> bool:
    raw = str(values.get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "enabled")


def env_int(values: Dict[str, str], key: str, default: int) -> int:
    try:
        return int(str(values.get(key, default)).strip())
    except (TypeError, ValueError):
        return default


def http_client(values: Optional[Dict[str, str]] = None) -> httpx.Client:
    values = values or load_env()
    use_http2 = env_bool(values, "NVIDIA_NIM_HTTP2", False)
    if HTTP_CLIENTS[use_http2] is None:
        try:
            HTTP_CLIENTS[use_http2] = httpx.Client(
                http2=use_http2,
                timeout=CLIENT_TIMEOUT,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=50, keepalive_expiry=120.0),
            )
        except ImportError:
            sys.stderr.write("[http] HTTP/2 requested but h2 is not installed; falling back to HTTP/1.1\n")
            use_http2 = False
            if HTTP_CLIENTS[False] is None:
                HTTP_CLIENTS[False] = httpx.Client(
                    http2=False,
                    timeout=CLIENT_TIMEOUT,
                    follow_redirects=True,
                    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50, keepalive_expiry=120.0),
                )
    return HTTP_CLIENTS[use_http2]


def validate_provider_ready(provider):
    if not provider.base_url:
        raise ProxyError(f"{provider.name}_BASE_URL is empty")
    if provider.needs_key and (not provider.api_key or "your-key" in provider.api_key or provider.api_key == "your-api-key"):
        raise ProxyError("NVIDIA_NIM_API is missing or still a placeholder")
    if not provider.model:
        raise ProxyError("NVIDIA_NIM_MODEL is empty. Select a model in the Admin UI.")


def _retry_delay(attempt: int) -> float:
    return 0.25 * (attempt + 1)


def call_openai_compatible(provider, body: Dict[str, Any], values: Optional[Dict[str, str]] = None):
    validate_provider_ready(provider)
    url = provider.base_url.rstrip("/") + "/chat/completions"
    values = values or load_env()
    client = http_client(values)

    if body.get("stream"):
        return client.stream("POST", url, json=body, headers=provider_headers(provider), timeout=STREAM_TIMEOUT)

    attempts = int(values.get("NVIDIA_NIM_RETRIES", "2") or "2") + 1
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            resp = client.post(url, json=body, headers=provider_headers(provider), timeout=CLIENT_TIMEOUT)
            if resp.status_code in RETRYABLE_HTTP_STATUS and attempt + 1 < attempts:
                resp.close()
                time.sleep(_retry_delay(attempt))
                continue
            return resp
        except RETRYABLE_EXC as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(_retry_delay(attempt))
    raise last_exc or ProxyError("NVIDIA NIM request failed")


@contextmanager
def stream_openai_compatible(provider, body: Dict[str, Any], values: Optional[Dict[str, str]] = None):
    values = values or load_env()
    attempts = int(values.get("NVIDIA_NIM_STREAM_RETRIES", "1") or "1") + 1
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, attempts)):
        try:
            with call_openai_compatible(provider, body, values) as resp:
                if resp.status_code in RETRYABLE_HTTP_STATUS and attempt + 1 < attempts:
                    resp.read()
                    time.sleep(_retry_delay(attempt))
                    continue
                yield resp
                return
        except RETRYABLE_EXC as exc:
            last_exc = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(_retry_delay(attempt))
    raise last_exc or ProxyError("NVIDIA NIM stream failed")


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


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10, values: Optional[Dict[str, str]] = None) -> Any:
    resp = http_client(values).get(url, headers=headers or {}, timeout=httpx.Timeout(connect=5.0, read=timeout, write=10.0, pool=5.0))
    resp.raise_for_status()
    return resp.json()


def list_provider_models(provider, values: Optional[Dict[str, str]] = None) -> tuple[list[str], str]:
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
    values = values or load_env()
    data = fetch_json(provider.base_url.rstrip("/") + "/models", provider_headers(provider, content_type=False), 10, values)
    for mid in extract_model_ids(data):
        _add_model_id(ids, mid)
    sources.append(f"native /models: {len(ids)}")

    # Public NVIDIA catalog feed is optional because it is slower and not needed
    # for Claude Code's actual completion requests.
    if env_bool(values, "NVIDIA_NIM_INCLUDE_PUBLIC_CATALOG", False):
        try:
            before = len(ids)
            catalog = fetch_json(NVIDIA_FEATURED_MODELS_URL, {}, 2, values)
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
        ordered, source = list_provider_models(provider, values)

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
    }
    # If Claude Code sends a built-in Anthropic model name, map it to the
    # configured upstream model. If the user selected a real /v1/models item,
    # use that upstream model id directly.
    if requested and requested not in aliases and not requested.startswith("claude-"):
        return requested
    return provider.model


def _text_from_anthropic_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def last_user_text(body: Dict[str, Any]) -> str:
    for msg in reversed(body.get("messages") or []):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return _text_from_anthropic_content(msg.get("content")).strip()
    return ""


def is_local_fast_greeting(body: Dict[str, Any], values: Dict[str, str]) -> bool:
    if not env_bool(values, "FREE_AGENTS_LOCAL_GREETINGS", True):
        return False
    choice = body.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in ("any", "tool"):
        return False
    text = last_user_text(body).lower().strip(" \t\r\n.!?")
    greetings = {
        "hi", "hello", "hey", "yo", "hii", "hiii", "hola", "greetings",
        "how are you", "how are you?", "who are you", "who are you?"
    }
    return text in greetings


def local_text_response(text: str, request_model: str) -> Dict[str, Any]:
    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": request_model or "free-claude-code",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": max(1, len(text.split()))},
    }


def prepare_upstream_body(body: Dict[str, Any], _values: Dict[str, str]) -> Dict[str, Any]:
    return dict(body)


class Handler(BaseHTTPRequestHandler):
    server_version = "FreeClaudeCode/1.1"
    protocol_version = "HTTP/1.1"

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
            return self._send(200, {"logs": list(LOG_QUEUE), "latency": LAST_LATENCY.get("value", 0.0), "first_byte": LAST_FIRST_BYTE.get("value", 0.0)})
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
            request_model = body.get("model") or values.get("ANTHROPIC_MODEL", "free-claude-code")

            if is_local_fast_greeting(body, values):
                text = values.get("FREE_AGENTS_GREETING_TEXT", "Hi! I am ready.")
                latency = time.time() - start_time
                LAST_LATENCY["value"] = latency
                LAST_FIRST_BYTE["value"] = latency
                self.log_message("Local fast greeting completed in %.3fs", latency)
                if body.get("stream"):
                    return self._stream_text_response(text, request_model, start_time)
                return self._send(200, local_text_response(text, request_model))

            upstream_body = prepare_upstream_body(body, values)
            upstream = build_openai_request(upstream_body, upstream_model, max_tokens)
            self.log_message(
                "Forwarding request: stream=%s model=%s messages=%d tools=%d max_tokens=%s approx_tokens=%d",
                bool(body.get("stream")),
                upstream_model,
                len(body.get("messages") or []),
                len(body.get("tools") or []),
                upstream.get("max_tokens"),
                estimate_tokens({"system": body.get("system"), "messages": body.get("messages"), "tools": body.get("tools")}),
            )

            if body.get("stream"):
                return self._stream_messages(provider, upstream, values, request_model, start_time)

            resp = call_openai_compatible(provider, upstream, values)
            resp.raise_for_status()
            data = resp.json()

            latency = time.time() - start_time
            LAST_LATENCY["value"] = latency
            self.log_message("Request completed in %.2fs", latency)

            return self._send(200, openai_to_anthropic(data, request_model))
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
        except httpx.TimeoutException as e:
            return self._send(504, {"type": "error", "error": {"type": "upstream_timeout", "message": f"NVIDIA NIM timed out: {e}"}})
        except httpx.HTTPError as e:
            return self._send(502, {"type": "error", "error": {"type": "upstream_network_error", "message": f"NVIDIA NIM connection failed: {e}"}})
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

    def _start_stream(self, request_model: str) -> bool:
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
            return False
        mid = "msg_" + uuid.uuid4().hex
        return self._sse("message_start", {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": request_model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})

    def _finish_empty_stream(self, start_time: float, finish: str = "end_turn"):
        self._sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": finish, "stop_sequence": None}, "usage": {"output_tokens": 0}})
        self._sse("message_stop", {"type": "message_stop"})
        latency = time.time() - start_time
        LAST_LATENCY["value"] = latency
        self.log_message("Stream completed in %.2fs", latency)
        self.close_connection = True

    def _stream_text_response(self, text: str, request_model: str, start_time: float):
        if not self._start_stream(request_model):
            return
        first = time.time() - start_time
        LAST_FIRST_BYTE["value"] = first
        self.log_message("First stream byte sent in %.3fs", first)
        self._sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        if text:
            self._sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})
        self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self._finish_empty_stream(start_time)

    def _stream_messages(self, provider, upstream: Dict[str, Any], values: Dict[str, str], request_model: str, start_time: float):
        if not self._start_stream(request_model):
            return
        first = time.time() - start_time
        LAST_FIRST_BYTE["value"] = first
        self.log_message("First stream byte sent in %.3fs before upstream response", first)
        try:
            with stream_openai_compatible(provider, upstream, values) as resp:
                if resp.status_code >= 400:
                    detail = resp.read().decode("utf-8", errors="replace")[:1200]
                    self._stream_text_after_start(f"NVIDIA NIM Error ({resp.status_code}): {detail}", start_time)
                    return
                resp.raise_for_status()
                self._pipe_stream(resp, request_model, start_time, started=True)
        except httpx.TimeoutException as e:
            self._stream_text_after_start(f"NVIDIA NIM timed out: {e}", start_time)
        except httpx.HTTPError as e:
            self._stream_text_after_start(f"NVIDIA NIM connection failed: {e}", start_time)
        except Exception as e:
            self._stream_text_after_start(f"Proxy error: {e}", start_time)

    def _stream_text_after_start(self, text: str, start_time: float):
        self._sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        self._sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})
        self._sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self._finish_empty_stream(start_time)

    def _pipe_stream(self, resp, request_model: str, start_time: float, started: bool = False):
        if not started and not self._start_stream(request_model):
            return
        finish = "end_turn"
        text_started = False
        text_index = 0
        tool_calls: Dict[int, Dict[str, str]] = {}
        first_byte = True
        stream_error = ""

        try:
            for line in resp.iter_lines():
                try:
                    if not line or not line.startswith("data:"):
                        continue
                    if first_byte:
                        upstream_first = time.time() - start_time
                        self.log_message("First upstream stream byte received in %.2fs", upstream_first)
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
        except httpx.HTTPError as e:
            stream_error = f"Upstream stream ended early: {e}"
            self.log_message("%s", stream_error)

        if stream_error and not text_started and not tool_calls:
            text_started = True
            self._sse("content_block_start", {"type": "content_block_start", "index": text_index, "content_block": {"type": "text", "text": ""}})
            self._sse("content_block_delta", {"type": "content_block_delta", "index": text_index, "delta": {"type": "text_delta", "text": stream_error}})
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
        local_greetings_checked = " checked" if env_bool(values, "FREE_AGENTS_LOCAL_GREETINGS", True) else ""
        last_model = values.get("LAST_MODEL", "")

        models = []
        try:
            if api_value and api_value != "your-api-key":
                models, _ = list_provider_models(provider, values)
        except Exception:
            pass

        if not models:
            models = FALLBACK_NVIDIA_NIM_MODELS
            if current_model and current_model not in models:
                models = [current_model] + models

        options = "".join(f'<option value="{html.escape(m)}"{ " selected" if m == current_model else ""}>{html.escape(m)}</option>' for m in models)

        latency_val = LAST_LATENCY.get("value", 0.0)
        first_byte_val = LAST_FIRST_BYTE.get("value", 0.0)
        latency_html = f"<p>Last request latency: <strong id='latencyVal'>{latency_val:.2f}s</strong></p>" if latency_val > 0 else "<p>Last request latency: <strong id='latencyVal'>N/A</strong></p>"
        first_byte_html = f"<p>Last first byte: <strong id='firstByteVal'>{first_byte_val:.2f}s</strong></p>" if first_byte_val > 0 else "<p>Last first byte: <strong id='firstByteVal'>N/A</strong></p>"

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
  {first_byte_html}
  <p>HTTP/2 Upstream: <strong>{"Enabled" if env_bool(values, "NVIDIA_NIM_HTTP2", False) else "Disabled (fast default)"}</strong></p>
  <p>Connection Pooling: <strong>Active</strong></p>
  <button type="button" class="secondary" style="margin-left:0;" onclick="refreshModels()">Refresh Model List</button>
</section>

<form id="configForm" method="post">
<section>
  <h3>NVIDIA NIM Settings</h3>
  <label>NVIDIA_NIM_API<input name="NVIDIA_NIM_API" value="{html.escape(mask(api_value))}" placeholder="your-api-key"></label>
  <label>Selected Model (NVIDIA_NIM_MODEL)<br><select name="NVIDIA_NIM_MODEL">{options}</select></label>
  <label style="display:flex;gap:.5rem;align-items:center;margin-bottom:1.5rem;"><input type="checkbox" name="FREE_AGENTS_LOCAL_GREETINGS" value="1"{local_greetings_checked} style="width:auto;margin:0;"> Instant local reply for tiny greetings</label>
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
    if (data.first_byte > 0) {{
      document.getElementById('firstByteVal').textContent = data.first_byte.toFixed(2) + 's';
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
            resp = http_client(values).get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=FAST_TIMEOUT)
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
        allowed = {"NVIDIA_NIM_API", "NVIDIA_NIM_MODEL", "FREE_AGENTS_LOCAL_GREETINGS"}
        for k, v in form.items():
            if k not in allowed:
                continue
            val = v[0].strip()
            # Keep old key if the user submitted the masked value.
            if k == "NVIDIA_NIM_API" and "…" in val:
                continue
            updates[k] = val
        if "FREE_AGENTS_LOCAL_GREETINGS" not in updates:
            updates["FREE_AGENTS_LOCAL_GREETINGS"] = "0"

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
