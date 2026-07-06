from __future__ import annotations

import json
import math
import time
import uuid
from typing import Any, Dict, List, Optional


def _text_from_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "\n".join(parts)


def _tool_result_content(block: Dict[str, Any]) -> str:
    c = block.get("content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for item in c:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                out.append(item.get("text", ""))
            else:
                out.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(out)
    return json.dumps(c, ensure_ascii=False)


def anthropic_messages_to_openai(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for msg in messages or []:
        role = msg.get("role")
        content = msg.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            out.append({"role": role, "content": ""})
            continue
        if role == "assistant":
            text = _text_from_blocks(content) or None
            calls = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls.append({
                        "id": b.get("id") or "call_" + uuid.uuid4().hex,
                        "type": "function",
                        "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input") or {})},
                    })
            item: Dict[str, Any] = {"role": "assistant", "content": text}
            if calls:
                item["tool_calls"] = calls
            out.append(item)
            continue
        pending_text: List[str] = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                pending_text.append(b.get("text", ""))
            elif b.get("type") == "tool_result":
                if pending_text:
                    out.append({"role": "user", "content": "\n".join(pending_text)})
                    pending_text = []
                out.append({"role": "tool", "tool_call_id": b.get("tool_use_id"), "content": _tool_result_content(b)})
        if pending_text:
            out.append({"role": role, "content": "\n".join(pending_text)})
    return out


def anthropic_tools_to_openai(tools: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(tools, list) or not tools:
        return None
    return [{
        "type": "function",
        "function": {
            "name": t.get("name"),
            "description": t.get("description", ""),
            "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
        },
    } for t in tools if isinstance(t, dict) and t.get("name")]


def system_to_openai(system: Any) -> List[Dict[str, str]]:
    if not system:
        return []
    if isinstance(system, str):
        return [{"role": "system", "content": system}]
    if isinstance(system, list):
        text = "\n".join(x if isinstance(x, str) else x.get("text", "") for x in system if x)
        return [{"role": "system", "content": text}] if text else []
    return []


def build_openai_request(body: Dict[str, Any], provider_model: str, default_max_tokens: int) -> Dict[str, Any]:
    req: Dict[str, Any] = {
        "model": provider_model,
        "messages": system_to_openai(body.get("system")) + anthropic_messages_to_openai(body.get("messages") or []),
        "max_tokens": body.get("max_tokens") or default_max_tokens,
        "stream": bool(body.get("stream")),
    }
    for k in ("temperature", "top_p", "stop"):
        if k in body and body[k] is not None:
            req[k] = body[k]
    tools = anthropic_tools_to_openai(body.get("tools"))
    if tools:
        req["tools"] = tools
    tc = body.get("tool_choice")
    if isinstance(tc, dict):
        if tc.get("type") == "auto":
            req["tool_choice"] = "auto"
        elif tc.get("type") == "any":
            req["tool_choice"] = "required"
        elif tc.get("type") == "tool" and tc.get("name"):
            req["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
    return req


def finish_to_stop_reason(finish: Optional[str]) -> str:
    if finish == "tool_calls":
        return "tool_use"
    if finish == "length":
        return "max_tokens"
    if finish == "content_filter":
        return "stop_sequence"
    return "end_turn"


def openai_to_anthropic(data: Dict[str, Any], request_model: str) -> Dict[str, Any]:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content: List[Dict[str, Any]] = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg.get("content")})
    for tc in msg.get("tool_calls") or []:
        args = tc.get("function", {}).get("arguments") or "{}"
        try:
            parsed = json.loads(args)
        except Exception:
            parsed = {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id") or "toolu_" + uuid.uuid4().hex,
            "name": tc.get("function", {}).get("name"),
            "input": parsed,
        })
    if not content:
        content = [{"type": "text", "text": ""}]
    usage = data.get("usage") or {}
    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": request_model or "free-claude-code",
        "content": content,
        "stop_reason": finish_to_stop_reason(choice.get("finish_reason")),
        "stop_sequence": None,
        "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)},
    }


def estimate_tokens(obj: Any) -> int:
    text = json.dumps(obj, ensure_ascii=False)
    return max(1, math.ceil(len(text) / 4))
