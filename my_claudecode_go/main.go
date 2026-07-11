package main

import (
	"fmt"
	"log"

	"github.com/valyala/fasthttp"
)

func main() {
	configMap := LoadEnv()
	host := getWithDefault(configMap, "HOST", DefaultHost)
	port := getWithDefault(configMap, "PORT", DefaultPort)
	addr := host + ":" + port

	// Initialize dynamic config from environment
	dynamicConfig := &Config{
		NvidiaNimApi:    getWithDefault(configMap, "NVIDIA_NIM_API", ""),
		NvidiaNimModel:   getWithDefault(configMap, "NVIDIA_NIM_MODEL", DefaultNvidiaNimModel),
		NvidiaNimBaseUrl: getWithDefault(configMap, "NVIDIA_NIM_BASE_URL", DefaultNvidiaNimBaseURL),
	}

	handler := &ProxyHandler{
		config: dynamicConfig,
	}

	fmt.Printf("Starting Go proxy server on http://%s\n", addr)
	fmt.Printf("Admin UI available at http://%s/admin\n", addr)

	if err := fasthttp.ListenAndServe(addr, handler.Handle); err != nil {
		log.Fatalf("Error in ListenAndServe: %s", err)
	}
}
