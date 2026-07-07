use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

pub const DEFAULT_NVIDIA_NIM_BASE_URL: &str = "https://integrate.api.nvidia.com/v1";
pub const DEFAULT_NVIDIA_NIM_MODEL: &str = "meta/llama-3.1-8b-instruct";
pub const DEFAULT_OPENROUTER_BASE_URL: &str = "https://openrouter.ai/api/v1";
pub const DEFAULT_OPENROUTER_MODEL: &str = "google/gemini-2.0-flash-exp:free";
pub const DEFAULT_HOST: &str = "127.0.0.1";
pub const DEFAULT_PORT: &str = "2424";
pub const DEFAULT_PROXY_PORT: &str = "2442";

#[derive(Clone, Serialize, Deserialize)]
pub struct Config {
    pub nvidia_api: String,
    pub nvidia_model: String,
    pub base_url: String,
    pub host: String,
    pub port: String,
    pub proxy_port: String,
}

pub fn app_home() -> PathBuf {
    if let Ok(home) = std::env::var("MY_FREE_AGENTS_HOME") {
        return PathBuf::from(home);
    }
    PathBuf::from(".")
}

pub fn load_config() -> Config {
    let home = app_home();
    let env_path = home.join(".env");
    let mut config_map = HashMap::new();

    if let Ok(content) = fs::read_to_string(env_path) {
        for line in content.lines() {
            if let Some((k, v)) = line.split_once('=') {
                config_map.insert(k.trim().to_string(), v.trim().to_string());
            }
        }
    }

    let provider = config_map.get("PROVIDER").cloned().unwrap_or_else(|| "NVIDIA_NIM".to_string()).to_uppercase();
    if provider == "OPENROUTER" {
         return Config {
            nvidia_api: config_map.get("OPENROUTER_API_KEY").cloned().unwrap_or_default(),
            nvidia_model: config_map.get("OPENROUTER_MODEL").cloned().unwrap_or_else(|| DEFAULT_OPENROUTER_MODEL.to_string()),
            base_url: config_map.get("OPENROUTER_BASE_URL").cloned().unwrap_or_else(|| DEFAULT_OPENROUTER_BASE_URL.to_string()),
            host: config_map.get("HOST").cloned().unwrap_or_else(|| DEFAULT_HOST.to_string()),
            port: config_map.get("PORT").cloned().unwrap_or_else(|| DEFAULT_PORT.to_string()),
            proxy_port: config_map.get("PROXY_PORT").cloned().unwrap_or_else(|| DEFAULT_PROXY_PORT.to_string()),
        };
    }

    Config {
        nvidia_api: config_map.get("NVIDIA_NIM_API").cloned().or_else(|| std::env::var("NVIDIA_NIM_API").ok()).unwrap_or_default(),
        nvidia_model: config_map.get("NVIDIA_NIM_MODEL").cloned().unwrap_or_else(|| DEFAULT_NVIDIA_NIM_MODEL.to_string()),
        base_url: config_map.get("NVIDIA_NIM_BASE_URL").cloned().unwrap_or_else(|| DEFAULT_NVIDIA_NIM_BASE_URL.to_string()),
        host: config_map.get("HOST").cloned().unwrap_or_else(|| DEFAULT_HOST.to_string()),
        port: config_map.get("PORT").cloned().unwrap_or_else(|| DEFAULT_PORT.to_string()),
        proxy_port: config_map.get("PROXY_PORT").cloned().unwrap_or_else(|| DEFAULT_PROXY_PORT.to_string()),
    }
}
