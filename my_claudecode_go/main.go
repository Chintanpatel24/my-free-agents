package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/user"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/joho/godotenv"
	"github.com/tidwall/gjson"
	"github.com/tidwall/sjson"
	"github.com/valyala/fasthttp"
)

var (
	DefaultHost    = "127.0.0.1"
	DefaultPort    = "2424"
	DefaultModel   = "meta/llama-3.1-8b-instruct"
	DefaultBaseURL = "https://integrate.api.nvidia.com/v1"
	LastLatency    float64
)

type Config struct {
	NvidiaAPI   string
	NvidiaModel string
	BaseURL     string
	Host        string
	Port        string
}

func getAppHome() string {
	if h := os.Getenv("MY_FREE_AGENTS_HOME"); h != "" {
		return h
	}
	usr, _ := user.Current()
	return filepath.Join(usr.HomeDir, ".my-free-agents", "claudecode")
}

func loadConfig() Config {
	home := getAppHome()
	godotenv.Load(filepath.Join(home, ".env"))

	conf := Config{
		NvidiaAPI:   os.Getenv("NVIDIA_NIM_API"),
		NvidiaModel: os.Getenv("NVIDIA_NIM_MODEL"),
		BaseURL:     os.Getenv("NVIDIA_NIM_BASE_URL"),
		Host:        os.Getenv("HOST"),
		Port:        os.Getenv("PORT"),
	}

	if conf.NvidiaModel == "" {
		conf.NvidiaModel = DefaultModel
	}
	if conf.BaseURL == "" {
		conf.BaseURL = DefaultBaseURL
	}
	if conf.Host == "" {
		conf.Host = DefaultHost
	}
	if conf.Port == "" {
		conf.Port = DefaultPort
	}

	sfp := filepath.Join(home, "settings.json")
	if b, err := os.ReadFile(sfp); err == nil {
		if val := gjson.GetBytes(b, "NVIDIA_NIM_MODEL").String(); val != "" {
			conf.NvidiaModel = val
		}
	}
	return conf
}

func handleMessages(ctx *fasthttp.RequestCtx, conf Config) {
	startTime := time.Now()
	body := ctx.PostBody()
	isStream := gjson.GetBytes(body, "stream").Bool()
	requestModel := gjson.GetBytes(body, "model").String()

	oaReq := buildOpenAIRequest(body, conf)
	url := strings.TrimRight(conf.BaseURL, "/") + "/chat/completions"

	req := fasthttp.AcquireRequest()
	resp := fasthttp.AcquireResponse()
	defer fasthttp.ReleaseRequest(req)
	defer fasthttp.ReleaseResponse(resp)

	req.SetRequestURI(url)
	req.Header.SetMethod("POST")
	req.Header.SetContentType("application/json")
	req.Header.Set("Authorization", "Bearer "+conf.NvidiaAPI)
	req.SetBody([]byte(oaReq))

	if isStream {
		handleStream(ctx, req, startTime, conf)
		return
	}

	if err := fasthttp.Do(req, resp); err != nil {
		ctx.Error(err.Error(), 500)
		return
	}

	latency := time.Since(startTime).Seconds()
	LastLatency = latency

	anthResp := mapOpenAIToAnthropic(resp.Body(), requestModel)
	ctx.SetContentType("application/json")
	ctx.SetBody([]byte(anthResp))
}

func buildOpenAIRequest(anthBody []byte, conf Config) string {
	res, _ := sjson.Set("{}", "model", conf.NvidiaModel)
	messages := gjson.GetBytes(anthBody, "messages").Array()
	var oaMessages []interface{}

	if system := gjson.GetBytes(anthBody, "system").String(); system != "" {
		oaMessages = append(oaMessages, map[string]string{"role": "system", "content": system})
	}

	for _, msg := range messages {
		role := msg.Get("role").String()
		content := msg.Get("content").String()
		oaMessages = append(oaMessages, map[string]string{"role": role, "content": content})
	}

	msgJSON, _ := json.Marshal(oaMessages)
	res, _ = sjson.SetRaw(res, "messages", string(msgJSON))
	res, _ = sjson.Set(res, "stream", gjson.GetBytes(anthBody, "stream").Bool())
	res, _ = sjson.Set(res, "max_tokens", 4096)

	return res
}

func mapOpenAIToAnthropic(oaBody []byte, reqModel string) string {
	choice := gjson.GetBytes(oaBody, "choices.0")
	text := choice.Get("message.content").String()

	res, _ := sjson.Set("{}", "id", "msg_"+uuid.New().String())
	res, _ = sjson.Set(res, "type", "message")
	res, _ = sjson.Set(res, "role", "assistant")
	res, _ = sjson.Set(res, "model", reqModel)

	content := []map[string]string{{"type": "text", "text": text}}
	contentJSON, _ := json.Marshal(content)
	res, _ = sjson.SetRaw(res, "content", string(contentJSON))
	res, _ = sjson.Set(res, "stop_reason", "end_turn")

	return res
}

func handleStream(ctx *fasthttp.RequestCtx, req *fasthttp.Request, startTime time.Time, conf Config) {
	ctx.SetContentType("text/event-stream")
	ctx.Response.Header.Set("Cache-Control", "no-cache")
	ctx.Response.Header.Set("Connection", "keep-alive")

	// Simplified streaming response for Anthropic compatibility
	fmt.Fprintf(ctx, "event: message_start\ndata: {\"type\": \"message_start\", \"message\": {\"id\": \"msg_go\", \"type\": \"message\", \"role\": \"assistant\", \"content\": [], \"usage\": {\"input_tokens\": 0, \"output_tokens\": 0}}}\n\n")
	fmt.Fprintf(ctx, "event: content_block_start\ndata: {\"type\": \"content_block_start\", \"index\": 0, \"content_block\": {\"type\": \"text\", \"text\": \"\"}}\n\n")
	fmt.Fprintf(ctx, "event: content_block_delta\ndata: {\"type\": \"content_block_delta\", \"index\": 0, \"delta\": {\"type\": \"text_delta\", \"text\": \"(Streaming from Go Proxy...)\"}}\n\n")
	fmt.Fprintf(ctx, "event: content_block_stop\ndata: {\"type\": \"content_block_stop\", \"index\": 0}\n\n")
	fmt.Fprintf(ctx, "event: message_delta\ndata: {\"type\": \"message_delta\", \"delta\": {\"stop_reason\": \"end_turn\"}}\n\n")
	fmt.Fprintf(ctx, "event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n")
}

func main() {
	conf := loadConfig()

	h := func(ctx *fasthttp.RequestCtx) {
		switch string(ctx.Path()) {
		case "/v1/messages":
			handleMessages(ctx, conf)
		case "/admin":
			ctx.SetContentType("text/html")
			ctx.SetBody([]byte("<h1>Go Proxy Admin</h1>"))
		case "/health", "/":
			ctx.SetBody([]byte(`{"ok": true}`))
		default:
			ctx.SetStatusCode(404)
		}
	}

	fmt.Printf("🚀 Go Proxy: http://%s:%s\n", conf.Host, conf.Port)
	fasthttp.ListenAndServe(conf.Host+":"+conf.Port, h)
}
