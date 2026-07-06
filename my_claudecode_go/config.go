package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/joho/godotenv"
)

const (
	AppName                    = "My Free Agents"
	DefaultNvidiaNimBaseURL   = "https://integrate.api.nvidia.com/v1"
	DefaultNvidiaNimModel     = "meta/llama-3.1-8b-instruct"
	DefaultHost                = "127.0.0.1"
	DefaultPort                = "2424"
	DefaultMaxTokens           = "4096"
)

func AppHome() string {
	if home := os.Getenv("MY_FREE_AGENTS_HOME"); home != "" {
		return home
	}
	if home := os.Getenv("FREE_CLAUDE_CODE_HOME"); home != "" {
		return home
	}
	// Fallback to parent of current dir (assuming we are in my_claudecode_go)
	ex, _ := os.Executable()
	return filepath.Dir(filepath.Dir(ex))
}

func EnvPath() string {
	return filepath.Join(AppHome(), ".env")
}

func SettingsPath() string {
	return filepath.Join(AppHome(), "settings.json")
}

func LoadSettings() map[string]string {
	settings := make(map[string]string)
	p := SettingsPath()
	if _, err := os.Stat(p); err == nil {
		data, err := os.ReadFile(p)
		if err == nil {
			json.Unmarshal(data, &settings)
		}
	}
	return settings
}

func SaveSettings(updates map[string]string) error {
	settings := LoadSettings()
	for k, v := range updates {
		settings[k] = v
	}
	data, err := json.MarshalIndent(settings, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(SettingsPath(), data, 0600)
}

func LoadEnv() map[string]string {
	env := make(map[string]string)
	// Load from .env file
	p := EnvPath()
	if _, err := os.Stat(p); err == nil {
		fileEnv, _ := godotenv.Read(p)
		for k, v := range fileEnv {
			env[k] = v
		}
	}
	// Layer OS environment
	for _, e := range os.Environ() {
		pair := strings.SplitN(e, "=", 2)
		if len(pair) == 2 {
			env[pair[0]] = pair[1]
		}
	}
	// Layer settings.json
	settings := LoadSettings()
	for k, v := range settings {
		env[k] = v
	}
	return env
}

func WriteEnvValues(updates map[string]string) error {
	p := EnvPath()
	env, _ := godotenv.Read(p)
	if env == nil {
		env = make(map[string]string)
	}

	apiUpdates := make(map[string]string)
	otherUpdates := make(map[string]string)

	for k, v := range updates {
		if k == "NVIDIA_NIM_API" || k == "NVIDIA_NIM_API_KEY" {
			apiUpdates[k] = v
		} else {
			otherUpdates[k] = v
		}
	}

	if len(otherUpdates) > 0 {
		SaveSettings(otherUpdates)
	}

	if len(apiUpdates) > 0 {
		for k, v := range apiUpdates {
			env[k] = v
		}
		api := env["NVIDIA_NIM_API"]
		if api == "" {
			api = env["NVIDIA_NIM_API_KEY"]
		}
		content := fmt.Sprintf("# NVIDIA NIM API Key\nNVIDIA_NIM_API=%s\n", api)
		os.WriteFile(p, []byte(content), 0600)
	}
	return nil
}

type ProviderConfig struct {
	Name     string
	BaseURL  string
	APIKey   string
	Model    string
	NeedsKey bool
}

func GetProvider(values map[string]string) ProviderConfig {
	model := values["NVIDIA_NIM_MODEL"]
	if model == "" {
		model = DefaultNvidiaNimModel
	}
	apiKey := values["NVIDIA_NIM_API"]
	if apiKey == "" {
		apiKey = values["NVIDIA_NIM_API_KEY"]
	}
	return ProviderConfig{
		Name:     "NVIDIA_NIM",
		BaseURL:  strings.TrimRight(getWithDefault(values, "NVIDIA_NIM_BASE_URL", DefaultNvidiaNimBaseURL), "/"),
		APIKey:   strings.TrimSpace(apiKey),
		Model:    strings.TrimSpace(model),
		NeedsKey: true,
	}
}

func getWithDefault(values map[string]string, key, defaultValue string) string {
	if val, ok := values[key]; ok && val != "" {
		return val
	}
	return defaultValue
}
