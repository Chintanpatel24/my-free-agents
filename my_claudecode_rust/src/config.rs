use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

pub const DEFAULT_NVIDIA_NIM_BASE_URL: &str = "https://integrate.api.nvidia.com/v1";
pub const DEFAULT_NVIDIA_NIM_MODEL: &str = "meta/llama-3.1-8b-instruct";
pub const DEFAULT_HOST: &str = "127.0.0.1";
pub const DEFAULT_PORT: &str = "2424";

#[derive(Clone, Serialize, Deserialize)]
pub struct Config {
    pub nvidia_api: String,
    pub nvidia_model: String,
    pub base_url: String,
    pub host: String,
    pub port: String,
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

    Config {
        nvidia_api: config_map.get("NVIDIA_NIM_API").cloned().or_else(|| std::env::var("NVIDIA_NIM_API").ok()).unwrap_or_default(),
        nvidia_model: config_map.get("NVIDIA_NIM_MODEL").cloned().unwrap_or_else(|| DEFAULT_NVIDIA_NIM_MODEL.to_string()),
        base_url: config_map.get("NVIDIA_NIM_BASE_URL").cloned().unwrap_or_else(|| DEFAULT_NVIDIA_NIM_BASE_URL.to_string()),
        host: config_map.get("HOST").cloned().unwrap_or_else(|| DEFAULT_HOST.to_string()),
        port: config_map.get("PORT").cloned().unwrap_or_else(|| DEFAULT_PORT.to_string()),
    }
}
