#include "json.hpp"
#include <string>

using json = nlohmann::json;

json build_openai_request(const json& anthropic, const std::string& model_id) {
    json messages = json::array();
    if (anthropic.contains("system") && anthropic["system"].is_string()) {
        messages.push_back({{"role", "system"}, {"content", anthropic["system"]}});
    }
    if (anthropic.contains("messages") && anthropic["messages"].is_array()) {
        for (const auto& msg : anthropic["messages"]) {
            messages.push_back({{"role", msg["role"]}, {"content", msg["content"]}});
        }
    }
    return {
        {"model", model_id},
        {"messages", messages},
        {"stream", anthropic.value("stream", false)},
        {"max_tokens", anthropic.value("max_tokens", 4096)}
    };
}

json openai_to_anthropic(const json& openai, const std::string& model_id) {
    auto choice = openai["choices"][0];
    auto message = choice["message"];

    return {
        {"id", "msg_cpp_test"},
        {"type", "message"},
        {"role", "assistant"},
        {"model", model_id},
        {"content", {{{"type", "text"}, {"text", message["content"]}}}},
        {"stop_reason", "end_turn"},
        {"usage", {
            {"input_tokens", openai["usage"]["prompt_tokens"]},
            {"output_tokens", openai["usage"]["completion_tokens"]}
        }}
    };
}
