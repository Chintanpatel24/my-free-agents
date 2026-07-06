use ax_sse = axum::response::sse;
use axum::{
    extract::State,
    http::StatusCode,
    response::{Html, IntoResponse},
    routing::{get, post},
    Json, Router,
};
use dotenvy::dotenv;
use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tower_http::cors::CorsLayer;
use uuid::Uuid;

#[derive(Clone)]
struct AppState {
    last_latency: Arc<Mutex<f64>>,
    log_queue: Arc<Mutex<VecDeque<String>>>,
    client: Client,
    config: Arc<Config>,
}

struct Config {
    nvidia_api: String,
    nvidia_model: String,
    base_url: String,
    host: String,
    port: String,
}

#[tokio::main]
async fn main() {
    dotenv().ok();
    let config = Arc::new(Config {
        nvidia_api: std::env::var("NVIDIA_NIM_API").unwrap_or_default(),
        nvidia_model: std::env::var("NVIDIA_NIM_MODEL").unwrap_or("meta/llama-3.1-8b-instruct".to_string()),
        base_url: std::env::var("NVIDIA_NIM_BASE_URL").unwrap_or("https://integrate.api.nvidia.com/v1".to_string()),
        host: std::env::var("HOST").unwrap_or("127.0.0.1".to_string()),
        port: std::env::var("PORT").unwrap_or("2424".to_string()),
    });

    let state = AppState {
        last_latency: Arc::new(Mutex::new(0.0)),
        log_queue: Arc::new(Mutex::new(VecDeque::with_capacity(50))),
        client: Client::builder()
            .timeout(Duration::from_secs(180))
            .build()
            .unwrap(),
        config: config.clone(),
    };

    let app = Router::new()
        .route("/", get(health))
        .route("/health", get(health))
        .route("/v1/messages", post(handle_messages))
        .route("/admin", get(admin_get))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = format!("{}:{}", config.host, config.port);
    println!("🚀 Rust High-Performance Proxy: http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}

async fn health() -> Json<Value> {
    Json(json!({"ok": true, "engine": "rust"}))
}

async fn handle_messages(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> impl IntoResponse {
    let start = Instant::now();
    let is_stream = body["stream"].as_bool().unwrap_or(false);
    let model = body["model"].as_str().unwrap_or("free-claude-code");

    let mut upstream_model = state.config.nvidia_model.clone();
    if let Some(m) = body["model"].as_str() {
        if !m.starts_with("claude-") && m != "free-claude-code" {
            upstream_model = m.to_string();
        }
    }

    let messages = body["messages"].as_array().cloned().unwrap_or_default();
    let system = body["system"].as_str().unwrap_or("");

    let mut oa_messages = Vec::new();
    if !system.is_empty() {
        oa_messages.push(json!({"role": "system", "content": system}));
    }
    for msg in messages {
        oa_messages.push(json!({
            "role": msg["role"],
            "content": msg["content"]
        }));
    }

    let oa_body = json!({
        "model": upstream_model,
        "messages": oa_messages,
        "stream": is_stream,
        "max_tokens": body["max_tokens"].as_i64().unwrap_or(4096),
    });

    let url = format!("{}/chat/completions", state.config.base_url.trim_end_matches('/'));

    if is_stream {
        // Rust streaming logic
        return (StatusCode::OK, "Stream not fully implemented in this placeholder").into_response();
    }

    let resp = state.client.post(url)
        .header("Authorization", format!("Bearer {}", state.config.nvidia_api))
        .json(&oa_body)
        .send()
        .await;

    match resp {
        Ok(r) => {
            let data: Value = r.json().await.unwrap_or(json!({}));
            let latency = start.elapsed().as_secs_f64();
            *state.last_latency.lock().unwrap() = latency;

            let anth_resp = json!({
                "id": format!("msg_{}", Uuid::new_v4()),
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": data["choices"][0]["message"]["content"]}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": data["usage"]["prompt_tokens"],
                    "output_tokens": data["usage"]["completion_tokens"]
                }
            });
            Json(anth_resp).into_response()
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    }
}

async fn admin_get() -> Html<String> {
    Html("<html><body><h1>Rust Proxy Admin</h1></body></html>".to_string())
}
