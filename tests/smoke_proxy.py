from __future__ import annotations

import json
import os
import tempfile
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FakeOpenAI(BaseHTTPRequestHandler):
    last_model = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_response(404); self.end_headers(); return
        data = {"object": "list", "data": [{"id": "fake-model"}, {"id": "fake-model-2"}, {"id": "claude-should-be-filtered"}, {"id": "anthropic/bad"}], "extra": {"models": [{"model": "nested-model-3"}]}}
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_response(404); self.end_headers(); return
        n = int(self.headers.get("Content-Length", "0") or "0")
        body = json.loads(self.rfile.read(n).decode() or "{}")
        FakeOpenAI.last_model = body.get("model")
        if body.get("stream"): 
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n')
            self.wfile.write(b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n')
            self.wfile.write(b'data: [DONE]\n\n')
            return
        data = {
            "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "hello from fake upstream"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
        raw = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def start_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        os.environ["FREE_CLAUDE_CODE_HOME"] = td
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        start_server(fake)
        fake_port = fake.server_address[1]

        os.environ["NVIDIA_NIM_BASE_URL"] = f"http://127.0.0.1:{fake_port}/v1"
        os.environ["NVIDIA_NIM_MODEL"] = "fake-model"
        os.environ["DEFAULT_MAX_TOKENS"] = "256"
        os.environ["FREE_AGENTS_LOCAL_GREETINGS"] = "0"
        env = Path(td) / ".env"
        env.write_text("NVIDIA_NIM_API=nvapi-test-key\n", encoding="utf-8")

        from free_claude_code.server import run_server
        proxy = run_server("127.0.0.1", 0)
        start_server(proxy)
        proxy_port = proxy.server_address[1]

        models = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{proxy_port}/v1/models", timeout=10).read().decode())
        model_ids = [m["id"] for m in models["data"]]
        assert "fake-model" in model_ids and "fake-model-2" in model_ids and "nested-model-3" in model_ids, models
        assert not any(mid.startswith("claude-") or mid == "free-claude-code" for mid in model_ids), models
        models_alt = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{proxy_port}/models", timeout=10).read().decode())
        assert [m["id"] for m in models_alt["data"]] == model_ids, models_alt

        req_body = {
            "model": "free-claude-code",
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi"}],
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            data=json.dumps(req_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        assert data["type"] == "message", data
        assert data["content"][0]["text"] == "hello from fake upstream", data
        assert FakeOpenAI.last_model == "fake-model", FakeOpenAI.last_model

        req_body["model"] = "fake-model-2"
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            data=json.dumps(req_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        assert FakeOpenAI.last_model == "fake-model-2", FakeOpenAI.last_model

        req_body["stream"] = True
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/v1/messages",
            data=json.dumps(req_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        text = urllib.request.urlopen(req, timeout=10).read().decode()
        assert "message_start" in text and "hello" in text and "message_stop" in text, text

        proxy.shutdown(); fake.shutdown()
    print("smoke proxy OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
