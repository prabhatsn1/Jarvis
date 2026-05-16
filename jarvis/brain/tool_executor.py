"""Autonomous tool-calling loop for LLM function-calling.

Orchestrates: user message → model (with tools) → tool execution → model …
until the model returns a final text answer or max iterations are reached.
"""

import json
import logging
import time

from jarvis.brain import tools as tool_impls
from jarvis.brain.tool_schemas import get_enabled_schemas

log = logging.getLogger("jarvis.brain.tool_executor")

# Map tool name → callable
TOOL_DISPATCH = {
    "web_search": tool_impls.web_search,
    "read_file": tool_impls.read_file,
    "run_code": tool_impls.run_code,
    "get_schedule": tool_impls.get_schedule,
    "get_next_event": tool_impls.get_next_event,
    "browser_action": tool_impls.browser_action,
    "smart_home_control": tool_impls.smart_home_control,
    "run_command": tool_impls.run_command,
}

# Tools that need a longer execution timeout (browser navigation can take ~30 s)
_LONG_TIMEOUT_TOOLS = frozenset({"browser_action"})
LONG_TOOL_TIMEOUT = 60  # seconds


class ToolExecutor:
    """Runs the autonomous tool-calling loop on top of an LLM client."""

    def __init__(self, config: dict):
        self.max_iterations = int(config.get("max_tool_calls", 4))
        self.tool_timeout = int(config.get("tool_timeout_sec", 15))
        self.workspace_root = config.get("workspace_root")
        self.schemas = get_enabled_schemas(config)

    def run_tool(self, name: str, arguments: dict) -> str:
        """Execute a single tool call safely and return its output string."""
        func = TOOL_DISPATCH.get(name)
        if func is None:
            return f"Error: unknown tool '{name}'."

        # Inject config-level overrides
        if name == "read_file":
            arguments.setdefault("workspace_root", self.workspace_root)
        if name == "run_code":
            arguments.setdefault("timeout", self.tool_timeout)

        start = time.time()
        try:
            result = func(**arguments)
        except Exception as exc:
            log.error(f"Tool {name} crashed: {exc}")
            result = f"Error: tool '{name}' failed — {exc}"
        elapsed = time.time() - start

        log.info(f"Tool {name} completed in {elapsed:.2f}s (success={not result.startswith('Error')})")
        return result

    def execute_loop(self, client, messages: list) -> str:
        """Run the tool-calling loop.

        Args:
            client:  An object with a ``chat_with_tools(messages, tools)``
                     method that returns (content, tool_calls).
            messages: The conversation so far (system + user messages).

        Returns:
            Final plain-text assistant response.
        """
        if not self.schemas:
            log.info("No tool schemas enabled, skipping tool loop.")
            return None

        for iteration in range(self.max_iterations):
            log.info(f"Tool loop iteration {iteration + 1}/{self.max_iterations}")

            force_text = iteration == self.max_iterations - 1
            content, tool_calls = client.chat_with_tools(
                messages, self.schemas, force_text=force_text,
            )

            # Model returned a text response (no tool calls)
            if not tool_calls:
                if content:
                    return content.strip()
                return None

            # Append the assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls,
            })

            # Execute each tool call and append results
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}

                tool_output = self.run_tool(tool_name, args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": tool_output,
                })

        # Exhausted iterations — ask model for a final answer without tools
        log.info("Max tool iterations reached, forcing final response.")
        content, _ = client.chat_with_tools(messages, tools=[], force_text=True)
        return (content or "").strip() or None
