import unittest

from free_claude_code.server import (
    is_local_fast_greeting,
    prepare_upstream_body,
    selected_upstream_model,
)


class Provider:
    model = "slow-model"


class FastModeTests(unittest.TestCase):
    def test_exact_greeting_uses_local_fast_path(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        self.assertTrue(is_local_fast_greeting(body, {}))

    def test_required_tool_choice_disables_local_greeting(self):
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "tool_choice": {"type": "any"},
        }
        self.assertFalse(is_local_fast_greeting(body, {}))

    def test_fast_mode_caps_requested_max_tokens(self):
        body = {"max_tokens": 8192, "messages": [{"role": "user", "content": "write"}]}
        out = prepare_upstream_body(body, {"FREE_AGENTS_FAST_MAX_TOKENS": "512"})
        self.assertEqual(out["max_tokens"], 512)

    def test_small_model_alias_routes_to_fast_model(self):
        body = {"model": "claude-3-5-haiku-latest"}
        model = selected_upstream_model(body, Provider(), {"NVIDIA_NIM_FAST_MODEL": "fast-model"})
        self.assertEqual(model, "fast-model")


if __name__ == "__main__":
    unittest.main()
