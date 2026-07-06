import json
import unittest
from my_claudecode_python.anthropic import build_openai_request, openai_to_anthropic


class AnthropicConversionTests(unittest.TestCase):
    def test_build_openai_request_with_tool(self):
        body = {
            "system": "You are helpful",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"name": "read_file", "description": "read", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}],
        }
        out = build_openai_request(body, "model-x", 100)
        self.assertEqual(out["model"], "model-x")
        self.assertEqual(out["messages"][0]["role"], "system")
        self.assertEqual(out["tools"][0]["function"]["name"], "read_file")

    def test_openai_to_anthropic_tool_call(self):
        data = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"id": "call_1", "function": {"name": "x", "arguments": json.dumps({"a": 1})}}]}}]}
        out = openai_to_anthropic(data, "free-claude-code")
        self.assertEqual(out["stop_reason"], "tool_use")
        self.assertEqual(out["content"][0]["type"], "tool_use")


if __name__ == "__main__":
    unittest.main()
