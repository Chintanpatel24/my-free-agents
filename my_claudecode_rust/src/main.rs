mod config;
mod anthropic;
mod server;

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use crate::server::{AppState, create_router};

#[tokio::main]
async fn main() {
    let config = config::load_config();
    let addr = format!("{}:{}", config.host, config.proxy_port);

    let state = AppState {
        last_latency: Arc::new(Mutex::new(0.0)),
        log_queue: Arc::new(Mutex::new(VecDeque::with_capacity(50))),
        client: reqwest::Client::builder()
            .timeout(Duration::from_secs(180))
            .build()
            .unwrap(),
        config,
    };

    let app = create_router(state);

    println!("🚀 Rust Proxy Server: http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
