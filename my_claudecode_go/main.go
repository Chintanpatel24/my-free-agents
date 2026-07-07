package main

import (
	"fmt"
	"log"

	"github.com/valyala/fasthttp"
)

func main() {
	config := LoadEnv()
	host := getWithDefault(config, "HOST", DefaultHost)
	port := getWithDefault(config, "PROXY_PORT", DefaultProxyPort)
	addr := host + ":" + port

	handler := &ProxyHandler{Config: config}

	fmt.Printf("Starting Go proxy server on http://%s\n", addr)
	fmt.Printf("Admin UI available at http://%s/admin\n", addr)

	if err := fasthttp.ListenAndServe(addr, handler.Handle); err != nil {
		log.Fatalf("Error in ListenAndServe: %s", err)
	}
}
