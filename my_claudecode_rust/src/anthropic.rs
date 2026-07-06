use serde_json::{json, Value};
use uuid::Uuid;

pub fn build_openai_request(anthropic: Value, model_id: &str) -> Value {
    let mut messages = Vec::new();
    if let Some(system) = anthropic["system"].as_str() {
        messages.push(json!({"role": "system", "content": system}));
    }

    if let Some(msgs) = anthropic["messages"].as_array() {
        for msg in msgs {
            messages.push(json!({
                "role": msg["role"],
                "content": msg["content"]
            }));
        }
    }

    json!({
        "model": model_id,
        "messages": messages,
        "stream": anthropic["stream"].as_bool().unwrap_or(false),
        "max_tokens": anthropic["max_tokens"].as_i64().unwrap_or(4096),
        "temperature": anthropic["temperature"],
    })
}

pub fn openai_to_anthropic(openai: Value, model_id: &str) -> Value {
    let choice = &openai["choices"][0];
    let message = &choice["message"];

    json!({
        "id": format!("msg_rust_{}", Uuid::new_v4()),
        "type": "message",
        "role": "assistant",
        "model": model_id,
        "content": [{"type": "text", "text": message["content"]}],
        "stop_reason": if choice["finish_reason"] == "tool_calls" { "tool_use" } else { "end_turn" },
        "usage": {
            "input_tokens": openai["usage"]["prompt_tokens"],
            "output_tokens": openai["usage"]["completion_tokens"]
        }
    })
}
