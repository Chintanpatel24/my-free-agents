use axum::{
    extract::State,
    http::StatusCode,
    response::{sse::{Event, Sse}, Html, IntoResponse},
    routing::{get, post},
    Json, Router,
};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use crate::config::Config;
use crate::anthropic;
use tokio_stream::Stream;
use std::convert::Infallible;
use axum::extract::Request;
use tower_http::services::ServeDir;

#[derive(Clone)]
pub struct AppState {
    pub last_latency: Arc<Mutex<f64>>,
    pub log_queue: Arc<Mutex<VecDeque<String>>>,
    pub client: reqwest::Client,
    pub config: Arc<Mutex<Config>>,
}

pub fn create_router(state: AppState) -> Router {
    Router::new()
        .route("/", get(health))
        .route("/health", get(health))
        .route("/v1/models", get(handle_models))
        .route("/v1/messages", post(handle_messages))
        .route("/admin", get(admin_get))
        .route("/admin/save", post(admin_save))
        .nest_service("/admin/static", ServeDir::new("assets/admin"))
        .with_state(state)
}

async fn health() -> Json<Value> {
    Json(json!({"ok": true, "engine": "rust"}))
}

async fn handle_models(State(state): State<AppState>) -> Json<Value> {
    let config = state.config.lock().unwrap();
    Json(json!({
        "object": "list",
        "data": [
            {
                "id": config.nvidia_model,
                "type": "model",
            }
        ]
    }))
}

async fn handle_messages(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> impl IntoResponse {
    let start = Instant::now();
    let (model_id, nvidia_api, base_url) = {
        let config = state.config.lock().unwrap();
        (
            body["model"].as_str().unwrap_or(&config.nvidia_model).to_string(),
            config.nvidia_api.clone(),
            config.base_url.clone(),
        )
    };
    let is_stream = body["stream"].as_bool().unwrap_or(false);

    let oa_body = anthropic::build_openai_request(body, &model_id);
    let url = format!("{}/chat/completions", base_url.trim_end_matches('/'));

    if is_stream {
        let resp = state.client.post(url)
            .header("Authorization", format!("Bearer {}", nvidia_api))
            .json(&oa_body)
            .send()
            .await;

        match resp {
            Ok(r) => {
                let stream = r.bytes_stream().map(|result| {
                    match result {
                        Ok(bytes) => {
                            let text = String::from_utf8_lossy(&bytes);
                            Ok::<Event, Infallible>(Event::default().data(text.to_string()))
                        }
                        Err(_) => Ok::<Event, Infallible>(Event::default().data("error")),
                    }
                });
                Sse::new(stream).into_response()
            }
            Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
        }
    } else {
        let resp = state.client.post(url)
            .header("Authorization", format!("Bearer {}", nvidia_api))
            .json(&oa_body)
            .send()
            .await;

        match resp {
            Ok(r) => {
                let data: Value = r.json().await.unwrap_or(json!({}));
                let latency = start.elapsed().as_secs_f64();
                *state.last_latency.lock().unwrap() = latency;
                Json(anthropic::openai_to_anthropic(data, &model_id)).into_response()
            }
            Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
        }
    }
}

async fn admin_get() -> Html<String> {
    Html("<meta http-equiv=\"refresh\" content=\"0; url=/admin/static/index.html\">".to_string())
}

async fn admin_save(
    State(state): State<AppState>,
    Json(payload): Json<Value>,
) -> impl IntoResponse {
    let mut config = state.config.lock().unwrap();
    if let Some(api) = payload["nvidia_api"].as_str() { config.nvidia_api = api.to_string(); }
    if let Some(model) = payload["nvidia_model"].as_str() { config.nvidia_model = model.to_string(); }
    if let Some(url) = payload["base_url"].as_str() { config.base_url = url.to_string(); }

    StatusCode::OK
}
