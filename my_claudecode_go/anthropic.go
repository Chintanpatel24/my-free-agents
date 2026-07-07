package main

import (
	"encoding/json"
	"fmt"
	"strings"
)

type AnthropicMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
}

type AnthropicRequest struct {
	Model       string             `json:"model"`
	Messages    []AnthropicMessage `json:"messages"`
	System      any                `json:"system"`
	Stream      bool               `json:"stream"`
	MaxTokens   int                `json:"max_tokens"`
	StopSeqs    []string           `json:"stop_sequences,omitempty"`
	Temperature *float64           `json:"temperature,omitempty"`
	Tools       []any              `json:"tools,omitempty"`
	ToolChoice  any                `json:"tool_choice,omitempty"`
}

type OpenAIMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"`
	Name    string `json:"name,omitempty"`
}

type OpenAIRequest struct {
	Model       string          `json:"model"`
	Messages    []OpenAIMessage `json:"messages"`
	Stream      bool            `json:"stream"`
	MaxTokens   int             `json:"max_tokens"`
	Temperature *float64        `json:"temperature,omitempty"`
	Tools       []any           `json:"tools,omitempty"`
	ToolChoice  any             `json:"tool_choice,omitempty"`
}

func BuildOpenAIRequest(anthropic AnthropicRequest, modelID string, maxTokens int) OpenAIRequest {
	req := OpenAIRequest{
		Model:       modelID,
		Stream:      anthropic.Stream,
		MaxTokens:   anthropic.MaxTokens,
		Temperature: anthropic.Temperature,
		Tools:       anthropic.Tools,
		ToolChoice:  anthropic.ToolChoice,
	}
	if req.MaxTokens == 0 {
		req.MaxTokens = maxTokens
	}

	messages := []OpenAIMessage{}
	if anthropic.System != nil {
		systemText := ""
		switch v := anthropic.System.(type) {
		case string:
			systemText = v
		case []any:
			for _, part := range v {
				if m, ok := part.(map[string]any); ok && m["type"] == "text" {
					systemText += fmt.Sprint(m["text"])
				}
			}
		}
		if systemText != "" {
			messages = append(messages, OpenAIMessage{Role: "system", Content: systemText})
		}
	}

	for _, msg := range anthropic.Messages {
		messages = append(messages, OpenAIMessage{Role: msg.Role, Content: msg.Content})
	}
	req.Messages = messages
	return req
}

func EstimateTokens(anthropic AnthropicRequest) int {
	// Crude estimation
	count := 0
	if s, ok := anthropic.System.(string); ok {
		count += len(strings.Fields(s))
	}
	for _, m := range anthropic.Messages {
		if s, ok := m.Content.(string); ok {
			count += len(strings.Fields(s))
		}
	}
	return int(float64(count) * 1.3)
}

func OpenAIToAnthropic(openAIResponse map[string]any, modelID string) map[string]any {
	choices, _ := openAIResponse["choices"].([]any)
	if len(choices) == 0 {
		return map[string]any{"error": "no choices in response"}
	}
	choice := choices[0].(map[string]any)
	message := choice["message"].(map[string]any)

	content := []any{}
	if text, ok := message["content"].(string); ok && text != "" {
		content = append(content, map[string]any{"type": "text", "text": text})
	}

	toolCalls, _ := message["tool_calls"].([]any)
	for _, tc := range toolCalls {
		tcm := tc.(map[string]any)
		fn := tcm["function"].(map[string]any)
		var args map[string]any
		json.Unmarshal([]byte(fmt.Sprint(fn["arguments"])), &args)
		content = append(content, map[string]any{
			"type": "tool_use",
			"id":   tcm["id"],
			"name": fn["name"],
			"input": args,
		})
	}

	stopReason := "end_turn"
	if choice["finish_reason"] == "tool_calls" {
		stopReason = "tool_use"
	}

	return map[string]any{
		"id":           "msg_go_" + fmt.Sprint(openAIResponse["id"]),
		"type":         "message",
		"role":         "assistant",
		"model":        modelID,
		"content":      content,
		"stop_reason":  stopReason,
		"stop_sequence": nil,
		"usage": map[string]any{
			"input_tokens":  openAIResponse["usage"].(map[string]any)["prompt_tokens"],
			"output_tokens": openAIResponse["usage"].(map[string]any)["completion_tokens"],
		},
	}
}
