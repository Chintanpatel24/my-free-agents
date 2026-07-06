#include <iostream>
#include <string>
#include <map>
#include <fstream>
#include <cstdlib>

struct Config {
    std::string nvidia_api;
    std::string nvidia_model;
    std::string base_url;
    std::string host;
    std::string port;
};

Config load_config() {
    Config cfg;
    cfg.nvidia_api = std::getenv("NVIDIA_NIM_API") ? std::getenv("NVIDIA_NIM_API") : "";
    cfg.nvidia_model = std::getenv("NVIDIA_NIM_MODEL") ? std::getenv("NVIDIA_NIM_MODEL") : "meta/llama-3.1-8b-instruct";
    cfg.base_url = std::getenv("NVIDIA_NIM_BASE_URL") ? std::getenv("NVIDIA_NIM_BASE_URL") : "https://integrate.api.nvidia.com/v1";
    cfg.host = std::getenv("HOST") ? std::getenv("HOST") : "127.0.0.1";
    cfg.port = std::getenv("PORT") ? std::getenv("PORT") : "2424";
    return cfg;
}
