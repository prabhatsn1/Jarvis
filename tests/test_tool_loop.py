"""Integration tests for the LLM tool-calling loop with mocked model."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarvis.brain.tool_executor import ToolExecutor
from jarvis.brain.llm import LLMEngine


class FakeLLMClient:
    """Simulates an LLM that requests a tool call, then returns a final answer."""

    def __init__(self, tool_name, tool_args, final_answer):
        self._tool_name = tool_name
        self._tool_args = tool_args
        self._final_answer = final_answer
        self._call_count = 0

    def chat_with_tools(self, messages, tools, force_text=False):
        self._call_count += 1
        # First call: request a tool call
        if self._call_count == 1 and not force_text:
            tool_calls = [{
                "id": "call_001",
                "function": {
                    "name": self._tool_name,
                    "arguments": json.dumps(self._tool_args),
                },
            }]
            return "", tool_calls
        # Second call (or force_text): return final answer
        return self._final_answer, []


class TestToolLoop(unittest.TestCase):
    """Integration test: model → tool call → tool result → final answer."""

    def _make_executor(self, **overrides):
        config = {
            "max_tool_calls": 4,
            "tool_timeout_sec": 5,
            "workspace_root": str(Path(__file__).parent.parent),
            "web_search_enabled": True,
            "file_read_enabled": True,
            "code_exec_enabled": True,
        }
        config.update(overrides)
        return ToolExecutor(config)

    def test_run_code_loop(self):
        """Model asks to run code, gets output, returns final answer."""
        client = FakeLLMClient(
            tool_name="run_code",
            tool_args={"code": "print(3+5+8)"},
            final_answer="The sum is 16.",
        )
        executor = self._make_executor()
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "Run print(sum([3,5,8])) and tell me the output."},
        ]
        result = executor.execute_loop(client, messages)
        self.assertEqual(result, "The sum is 16.")

    def test_read_file_loop(self):
        """Model asks to read a file, gets content, returns summary."""
        client = FakeLLMClient(
            tool_name="read_file",
            tool_args={"path": str(Path(__file__).parent.parent / "README.md"),
                       "start_line": 1, "end_line": 10},
            final_answer="The README describes Jarvis, a desktop assistant.",
        )
        executor = self._make_executor()
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "Read README.md and summarize."},
        ]
        result = executor.execute_loop(client, messages)
        self.assertEqual(result, "The README describes Jarvis, a desktop assistant.")

    def test_max_iterations_reached(self):
        """Verify loop stops after max_tool_calls even if model keeps calling tools."""
        class AlwaysCallsTool:
            def chat_with_tools(self, messages, tools, force_text=False):
                if force_text or not tools:
                    return "I finally answered.", []
                return "", [{
                    "id": "call_x",
                    "function": {
                        "name": "run_code",
                        "arguments": json.dumps({"code": "print(1)"}),
                    },
                }]

        executor = self._make_executor(max_tool_calls=2)
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "Keep running code."},
        ]
        result = executor.execute_loop(AlwaysCallsTool(), messages)
        self.assertEqual(result, "I finally answered.")

    def test_unknown_tool_error(self):
        """Model asks for a tool that doesn't exist — gets an error message back."""
        client = FakeLLMClient(
            tool_name="nonexistent_tool",
            tool_args={},
            final_answer="Sorry, that tool doesn't exist.",
        )
        executor = self._make_executor()
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "Do something weird."},
        ]
        result = executor.execute_loop(client, messages)
        self.assertEqual(result, "Sorry, that tool doesn't exist.")
        # The tool message in the history should contain the error
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        self.assertTrue(any("unknown tool" in m["content"].lower() for m in tool_msgs))

    def test_no_schemas_skips_loop(self):
        """When all tools are disabled, loop returns None immediately."""
        executor = self._make_executor(
            web_search_enabled=False,
            file_read_enabled=False,
            code_exec_enabled=False,
            calendar_enabled=False,
        )
        messages = [
            {"role": "system", "content": "You are Jarvis."},
            {"role": "user", "content": "Hello"},
        ]
        result = executor.execute_loop(MagicMock(), messages)
        self.assertIsNone(result)


class TestExistingPipelineUnchanged(unittest.TestCase):
    """Verify deterministic command pipeline is not affected by tool-calling."""

    def test_llm_disabled(self):
        """LLMEngine with enabled=False returns None from query()."""
        engine = LLMEngine({"enabled": False})
        self.assertIsNone(engine.query("hello"))

    def test_function_calling_disabled(self):
        """Even with LLM enabled, function_calling_enabled=False skips tool loop."""
        config = {
            "enabled": True,
            "provider": "huggingface",
            "function_calling_enabled": False,
            "model": "test/model",
        }
        with patch("jarvis.brain.llm.LLMEngine._init_huggingface"):
            engine = LLMEngine(config)
            engine._client = MagicMock()
            self.assertIsNone(engine._tool_executor)


if __name__ == "__main__":
    unittest.main()
