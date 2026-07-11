package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"path/filepath"
	"sync"
	"time"
	"strings"

	"github.com/google/uuid"
	"github.com/valyala/fasthttp"
)

var (
	logQueue     []string
	logMutex     sync.Mutex
	lastLatency  float64
)

func logMsg(fmtStr string, args ...any) {
	msg := fmt.Sprintf("[%s] %s", time.Now().Format("02/Jan/2006 15:04:05"), fmt.Sprintf(fmtStr, args...))
	log.Println(msg)
	logMutex.Lock()
	logQueue = append(logQueue, msg)
	if len(logQueue) > 50 {
		logQueue = logQueue[1:]
	}
	logMutex.Unlock()
}

type Config struct {
	NvidiaNimApi    string
	NvidiaNimModel  string
	NvidiaNimBaseUrl string
}

type ProxyHandler struct {
	config *Config
	mu     sync.RWMutex
}

func (h *ProxyHandler) Handle(ctx *fasthttp.RequestCtx) {
	path := string(ctx.Path())
	switch {
	case path == "/" || path == "/health":
		h.handleHealth(ctx)
	case path == "/v1/models" || path == "/models":
		h.handleModels(ctx)
	case path == "/v1/messages":
		h.handleMessages(ctx)
	case path == "/admin":
		h.handleAdminGet(ctx)
	case strings.HasPrefix(path, "/admin/static/"):
		h.handleAdminStatic(ctx)
	case path == "/admin/save":
		h.handleAdminSave(ctx)
	case path == "/admin/logs":
		h.handleAdminLogs(ctx)
	case path == "/admin/test":
		h.handleAdminTest(ctx)
	default:
		ctx.SetStatusCode(404)
		fmt.Fprintf(ctx, `{"error": "not found"}`)
	}
}

func (h *ProxyHandler) handleHealth(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	h.mu.RLock()
	defer h.mu.RUnlock()
	fmt.Fprintf(ctx, `{"ok": true, "name": "free-agents-go", "provider": "NVIDIA_NIM", "model": "%s"}`, h.config.NvidiaNimModel)
}

func (h *ProxyHandler) handleModels(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	h.mu.RLock()
	model := h.config.NvidiaNimModel
	h.mu.RUnlock()

	models := []string{model, "meta/llama-3.1-8b-instruct", "meta/llama-3.1-70b-instruct", "meta/llama-3.3-70b-instruct"}

	data := map[string]any{
		"object": "list",
		"data":   formatModels(models),
	}
	json.NewEncoder(ctx).Encode(data)
}

func formatModels(ids []string) []map[string]any {
	res := []map[string]any{}
	for _, id := range ids {
		res = append(res, map[string]any{
			"id":           id,
			"type":         "model",
			"display_name": id,
		})
	}
	return res
}

func (h *ProxyHandler) handleMessages(ctx *fasthttp.RequestCtx) {
	startTime := time.Now()
	var anthropicReq AnthropicRequest
	if err := json.Unmarshal(ctx.PostBody(), &anthropicReq); err != nil {
		ctx.SetStatusCode(400)
		return
	}

	h.mu.RLock()
	modelID := h.config.NvidiaNimModel
	apiKey := h.config.NvidiaNimApi
	baseURL := h.config.NvidiaNimBaseUrl
	h.mu.RUnlock()

	if anthropicReq.Model != "" && !strings.HasPrefix(anthropicReq.Model, "claude-") {
		modelID = anthropicReq.Model
	}

	openaiReq := BuildOpenAIRequest(anthropicReq, modelID, 4096)

	logMsg("Forwarding request: stream=%v model=%s", anthropicReq.Stream, modelID)

	if anthropicReq.Stream {
		// We need to pass provider info to handleStream
		provider := ProviderConfig{
			Name:     "NVIDIA_NIM",
			BaseURL:  baseURL,
			APIKey:   apiKey,
			Model:    modelID,
			NeedsKey: true,
		}
		h.handleStream(ctx, provider, openaiReq, startTime)
		return
	}

	client := &fasthttp.Client{}
	req := fasthttp.AcquireRequest()
	resp := fasthttp.AcquireResponse()
	defer fasthttp.ReleaseRequest(req)
	defer fasthttp.ReleaseResponse(resp)

	req.SetRequestURI(baseURL + "/chat/completions")
	req.Header.SetMethod("POST")
	req.Header.SetContentType("application/json")
	req.Header.Set("Authorization", "Bearer "+apiKey)
	body, _ := json.Marshal(openaiReq)
	req.SetBody(body)

	if err := client.Do(req, resp); err != nil {
		ctx.SetStatusCode(500)
		return
	}

	var oaResp map[string]any
	json.Unmarshal(resp.Body(), &oaResp)

	lastLatency = time.Since(startTime).Seconds()
	logMsg("Request completed in %.2fs", lastLatency)

	ctx.SetContentType("application/json")
	json.NewEncoder(ctx).Encode(OpenAIToAnthropic(oaResp, anthropicReq.Model))
}

func (h *ProxyHandler) handleStream(ctx *fasthttp.RequestCtx, provider ProviderConfig, openaiReq OpenAIRequest, startTime time.Time) {
	ctx.SetContentType("text/event-stream")
	ctx.Response.Header.Set("Cache-Control", "no-cache")
	ctx.Response.Header.Set("Connection", "keep-alive")

	msgID := "msg_go_" + uuid.New().String()
	fmt.Fprintf(ctx, "event: message_start\ndata: %s\n\n", `{"type": "message_start", "message": {"id": "`+msgID+`", "type": "message", "role": "assistant", "content": []}}`)

	client := &fasthttp.Client{}
	req := fasthttp.AcquireRequest()
	resp := fasthttp.AcquireResponse()
	defer fasthttp.ReleaseRequest(req)
	defer fasthttp.ReleaseResponse(resp)

	req.SetRequestURI(provider.BaseURL + "/chat/completions")
	req.Header.SetMethod("POST")
	req.Header.SetContentType("application/json")
	req.Header.Set("Authorization", "Bearer "+provider.APIKey)
	body, _ := json.Marshal(openaiReq)
	req.SetBody(body)

	if err := client.Do(req, resp); err != nil {
		logMsg("Upstream request failed: %v", err)
		return
	}

	reader := bytes.NewReader(resp.Body())
	scanner := bufio.NewScanner(reader)
	textStarted := false

	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data: ") {
			continue
		}
		data := strings.TrimPrefix(line, "data: ")
		if data == "[DONE]" {
			break
		}

		var chunk map[string]any
		if err := json.Unmarshal([]byte(data), &chunk); err != nil {
			continue
		}

		choices := chunk["choices"].([]any)
		if len(choices) == 0 {
			continue
		}
		choice := choices[0].(map[string]any)
		delta := choice["delta"].(map[string]any)
		content, _ := delta["content"].(string)

		if content != "" {
			if !textStarted {
				textStarted = true
				fmt.Fprintf(ctx, "event: content_block_start\ndata: %s\n\n", `{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}`)
			}
			fmt.Fprintf(ctx, "event: content_block_delta\ndata: {\"type\": \"content_block_delta\", \"index\": 0, \"delta\": {\"type\": \"text_delta\", \"text\": %q}}\n\n", content)
		}
	}

	if textStarted {
		fmt.Fprintf(ctx, "event: content_block_stop\ndata: {\"type\": \"content_block_stop\", \"index\": 0}\n\n")
	}
	fmt.Fprintf(ctx, "event: message_delta\ndata: {\"type\": \"message_delta\", \"delta\": {\"stop_reason\": \"end_turn\"}}\n\n")
	fmt.Fprintf(ctx, "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n")
}

func (h *ProxyHandler) handleAdminGet(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("text/html")
	ctx.Redirect("/admin/static/index.html", 302)
}

func (h *ProxyHandler) handleAdminSave(ctx *fasthttp.RequestCtx) {
	var payload struct {
		NvidiaApi    string `json:"nvidia_api"`
		NvidiaModel  string `json:"nvidia_model"`
		NvidiaBaseUrl string `json:"base_url"`
	}
	if err := json.Unmarshal(ctx.PostBody(), &payload); err != nil {
		ctx.SetStatusCode(400)
		return
	}

	h.mu.Lock()
	if payload.NvidiaApi != "" {
		h.config.NvidiaNimApi = payload.NvidiaApi
	}
	if payload.NvidiaModel != "" {
		h.config.NvidiaNimModel = payload.NvidiaModel
	}
	if payload.NvidiaBaseUrl != "" {
		h.config.NvidiaNimBaseUrl = payload.NvidiaBaseUrl
	}
	h.mu.Unlock()

	ctx.SetContentType("application/json")
	fmt.Fprint(ctx, `{"ok": true}`)
}

func (h *ProxyHandler) handleAdminStatic(ctx *fasthttp.RequestCtx) {
	path := string(ctx.Path())
	// Strip /admin/static/ prefix
	filePath := path[len("/admin/static/"):]
	if filePath == "" {
		filePath = "index.html"
	}

	// Serve from assets/admin
	fullPath := filepath.Join("assets", "admin", filePath)
	fasthttp.ServeFile(ctx, fullPath)
}

func (h *ProxyHandler) handleAdminLogs(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	logMutex.Lock()
	defer logMutex.Unlock()
	json.NewEncoder(ctx).Encode(map[string]any{
		"logs": logQueue,
		"latency": lastLatency,
	})
}

func (h *ProxyHandler) handleAdminTest(ctx *fasthttp.RequestCtx) {
	ctx.SetContentType("application/json")
	fmt.Fprint(ctx, `{"ok": true}`)
}
