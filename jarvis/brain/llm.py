import os
import logging
from collections import deque

from jarvis.brain.tool_executor import ToolExecutor

log = logging.getLogger("jarvis.brain.llm")

SYSTEM_PROMPT = (
    "You are Jarvis, a concise voice assistant. "
    "Reply in 1-2 short sentences. Be direct and conversational. "
    "Do not use markdown, bullet points, or special formatting."
)

SYSTEM_PROMPT_WITH_TOOLS = (
    "You are Jarvis, a concise voice assistant with access to tools. "
    "Use tools when you need real-time info, file contents, or code output. "
    "After getting tool results, reply in 1-2 short spoken sentences. "
    "Do not use markdown, bullet points, or special formatting."
)

# ── Tone adaptation modifiers appended to system prompt ──────────────────────
_TONE_MODIFIERS: dict[str, str] = {
    "urgent": (
        " The user sounds urgent — respond immediately with the most critical "
        "information first. Be brief and action-oriented."
    ),
    "frustrated": (
        " The user sounds frustrated. Be empathetic, calm, and extra clear. "
        "Acknowledge the issue briefly before giving the answer."
    ),
    "normal": "",
}


class ConversationHistory:
    """Rolling conversation history for mid-session context."""

    def __init__(self, max_turns: int = 20):
        self._history: deque[dict] = deque(maxlen=max_turns * 2)

    def add_user(self, text: str):
        self._history.append({"role": "user", "content": text})

    def add_assistant(self, text: str):
        self._history.append({"role": "assistant", "content": text})

    def get_messages(self, system_content: str) -> list[dict]:
        """Return full message list: system + history (without latest user msg)."""
        return [{"role": "system", "content": system_content}] + list(self._history)

    def clear(self):
        self._history.clear()


class LLMEngine:
    """LLM fallback for unmatched voice commands.

    Supports three providers:
      - ``huggingface`` (default) — HuggingFace Inference API
      - ``openai``                — OpenAI official API
      - ``openai_compatible``     — any OpenAI-compatible endpoint
    """

    def __init__(self, config: dict):
        self._client = None
        self._openai_client = None
        self.enabled = config.get("enabled", False)
        self._provider = config.get("provider", "huggingface")
        self._function_calling = config.get("function_calling_enabled", False)
        self._tool_executor = None
        self._config = config

        # Conversation history
        max_turns = int(config.get("conversation_history_turns", 20))
        self._history = ConversationHistory(max_turns=max_turns)
        self._current_emotion: str = "normal"  # updated per-turn by core.py

        if not self.enabled:
            log.info("LLM engine disabled.")
            return

        if self._provider == "openai":
            self._init_openai_official(config)
        elif self._provider == "openai_compatible":
            self._init_openai(config)
        else:
            self._init_huggingface(config)

        # Tool executor (only when function calling is on and client is ready)
        if self._function_calling and (self._client or self._openai_client):
            self._tool_executor = ToolExecutor(config)
            log.info("Function-calling enabled.")

    # ── provider init ─────────────────────────────────────────────

    def _init_huggingface(self, config: dict):
        try:
            from huggingface_hub import InferenceClient
        except ImportError:
            log.error(
                "huggingface_hub is not installed. "
                "Run: pip install huggingface_hub"
            )
            self.enabled = False
            return

        model = config.get("model", "mistralai/Mistral-7B-Instruct-v0.3")
        token = config.get("api_token") or os.environ.get("HF_TOKEN")
        self._client = InferenceClient(model=model, token=token or None)
        self._max_tokens = int(config.get("max_new_tokens", 150))
        log.info(f"LLM engine ready (huggingface) — model: {model}")

    def _init_openai_official(self, config: dict):
        try:
            from openai import OpenAI
        except ImportError:
            log.error("openai is not installed. Run: pip install openai")
            self.enabled = False
            return

        api_key = config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            log.error("OpenAI API key not set. Set openai_api_key in config or OPENAI_API_KEY env var.")
            self.enabled = False
            return

        self._openai_model = config.get("openai_model", "gpt-4o-mini")
        self._max_tokens = int(config.get("max_new_tokens", 150))

        self._openai_client = OpenAI(api_key=api_key)
        log.info(f"LLM engine ready (openai) — model: {self._openai_model}")

    def _init_openai(self, config: dict):
        try:
            from openai import OpenAI
        except ImportError:
            log.error(
                "openai is not installed. Run: pip install openai"
            )
            self.enabled = False
            return

        base_url = config.get("openai_base_url", "http://localhost:1234/v1")
        api_key = config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "no-key")
        self._openai_model = config.get("openai_model", "gpt-3.5-turbo")
        self._max_tokens = int(config.get("max_new_tokens", 150))

        self._openai_client = OpenAI(base_url=base_url, api_key=api_key)
        log.info(f"LLM engine ready (openai_compatible) — model: {self._openai_model}")

    # ── public API ────────────────────────────────────────────────

    def query(self, text: str, context_facts: list[str] | None = None) -> str | None:
        """Send *text* to the LLM and return a spoken response string.

        When function-calling is enabled, runs an autonomous tool loop
        before returning the final answer.
        """
        if not self.enabled:
            return None

        # Add user message to history
        self._history.add_user(text)

        # Try function-calling path first
        if self._function_calling and self._tool_executor:
            answer = self._query_with_tools(text)
            if answer:
                self._history.add_assistant(answer)
                return answer

        # Plain query (no tools, or tool path failed/disabled)
        answer = self._plain_query(text, context_facts=context_facts)
        if answer:
            self._history.add_assistant(answer)
        return answer

    def set_tone(self, emotion: str) -> None:
        """Set the current emotional tone to adapt the system prompt.

        Parameters
        ----------
        emotion:
            One of ``"normal"``, ``"urgent"``, or ``"frustrated"``.
            Unknown values fall back to ``"normal"``.
        """
        self._current_emotion = emotion if emotion in _TONE_MODIFIERS else "normal"
        if self._current_emotion != "normal":
            log.info("Tone set to: %s", self._current_emotion)

    def clear_history(self):
        """Clear conversation history (e.g. on session end)."""
        self._history.clear()
        self._current_emotion = "normal"
        log.info("Conversation history cleared.")

    # ── chat_with_tools interface ─────────────────────────────────
    # Used by ToolExecutor.execute_loop() as the LLM client.

    def chat_with_tools(self, messages, tools, force_text=False):
        """Send messages+tools to model. Returns (content, tool_calls).

        ``tool_calls`` is a list of dicts with ``id``, ``function.name``,
        ``function.arguments`` — or an empty list when none are requested.
        """
        if self._openai_client:
            return self._openai_chat_with_tools(messages, tools, force_text)
        return self._hf_chat_with_tools(messages, tools, force_text)

    # ── internal: plain query ─────────────────────────────────────

    def _plain_query(self, text: str, context_facts: list[str] | None = None) -> str | None:
        tone_modifier = _TONE_MODIFIERS.get(self._current_emotion, "")
        system_content = SYSTEM_PROMPT + tone_modifier
        if context_facts:
            facts_block = (
                "Relevant things you know about the user:\n"
                + "\n".join(f"- {f}" for f in context_facts)
                + "\n\n"
            )
            system_content = facts_block + system_content

        # Build messages with conversation history for context
        messages = self._history.get_messages(system_content)

        if self._openai_client:
            return self._openai_plain(messages)
        if self._client:
            return self._hf_plain(messages)
        return None

    def _hf_plain(self, messages) -> str | None:
        try:
            completion = self._client.chat_completion(
                messages=messages,
                max_tokens=self._max_tokens,
            )
            answer = completion.choices[0].message.content.strip()
            log.info(f"LLM response: {answer!r}")
            return answer
        except Exception as exc:
            log.warning(f"LLM query failed: {exc}")
            return None

    def _openai_plain(self, messages) -> str | None:
        try:
            completion = self._openai_client.chat.completions.create(
                model=self._openai_model,
                messages=messages,
                max_tokens=self._max_tokens,
            )
            answer = completion.choices[0].message.content.strip()
            log.info(f"LLM response: {answer!r}")
            return answer
        except Exception as exc:
            log.warning(f"LLM query failed: {exc}")
            return None

    # ── internal: tool-augmented query ────────────────────────────

    def _query_with_tools(self, text: str) -> str | None:
        # Include conversation history and tone modifier for tool-augmented queries
        tone_modifier = _TONE_MODIFIERS.get(self._current_emotion, "")
        messages = self._history.get_messages(SYSTEM_PROMPT_WITH_TOOLS + tone_modifier)
        try:
            return self._tool_executor.execute_loop(self, messages)
        except Exception as exc:
            log.warning(f"Tool loop failed, falling back to plain query: {exc}")
            return None

    # ── OpenAI-compatible tool calling ────────────────────────────

    def _openai_chat_with_tools(self, messages, tools, force_text):
        try:
            kwargs = {
                "model": self._openai_model,
                "messages": messages,
                "max_tokens": self._max_tokens,
            }
            if tools and not force_text:
                kwargs["tools"] = tools
            completion = self._openai_client.chat.completions.create(**kwargs)
            choice = completion.choices[0]
            content = choice.message.content or ""
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
            return content, tool_calls
        except Exception as exc:
            log.warning(f"OpenAI chat_with_tools failed: {exc}")
            return "", []

    # ── HuggingFace tool calling ──────────────────────────────────

    def _hf_chat_with_tools(self, messages, tools, force_text):
        try:
            kwargs = {
                "messages": messages,
                "max_tokens": self._max_tokens,
            }
            if tools and not force_text:
                kwargs["tools"] = tools
            completion = self._client.chat_completion(**kwargs)
            choice = completion.choices[0]
            content = choice.message.content or ""
            tool_calls = []
            if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "id": getattr(tc, "id", ""),
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    })
            return content, tool_calls
        except Exception as exc:
            log.warning(f"HF chat_with_tools failed: {exc}")
            # Graceful degradation — fall back to plain response
            return "", []
