"""
anthropic_provider.py — Anthropic Claude provider implementation.

Key design points:
  - ONE AsyncAnthropic client created at __init__ time, reused forever.
  - System messages are separated from the message list (Anthropic API requirement).
  - finish_reason normalized: "end_turn" → "stop", "max_tokens" → "length".
  - count_tokens uses tiktoken cl100k_base locally — zero API calls (approximation).
"""
from typing import Dict, List, Optional

import tiktoken

from .base import BaseLLMProvider, LLMResponse, Message


class AnthropicProvider(BaseLLMProvider):

    _CONTEXT_WINDOWS: Dict[str, int] = {
        "claude-opus-4-6":          200_000,
        "claude-sonnet-4-6":        200_000,
        "claude-haiku-4-5-20251001": 200_000,
        "claude-3-5-sonnet-20241022": 200_000,
        "claude-3-5-haiku-20241022":  200_000,
        "claude-3-opus-20240229":    200_000,
        "claude-3-sonnet-20240229":  200_000,
        "claude-3-haiku-20240307":   200_000,
    }

    # Anthropic does not expose a public tokenizer; cl100k_base is a good approximation
    _TIKTOKEN_APPROX = "cl100k_base"

    def __init__(self, model: str, api_key: str):
        import anthropic  # lazy import so package is optional if not using Anthropic
        self.model = model
        self.context_window = self._CONTEXT_WINDOWS.get(model, 200_000)
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._enc = tiktoken.get_encoding(self._TIKTOKEN_APPROX)

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        # Anthropic requires system messages to be passed separately
        system_parts = [m.content for m in messages if m.role == "system"]
        chat_messages = [
            {"role": m.role, "content": m.content}
            for m in messages if m.role != "system"
        ]

        kwargs = dict(
            model=self.model,
            messages=chat_messages,
            temperature=temperature,
            max_tokens=max_output_tokens or 4096,
        )
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)

        response = await self._client.messages.create(**kwargs)
        block = response.content[0] if response.content else None
        content = block.text if block and hasattr(block, "text") else ""

        # Normalize stop reasons
        raw_stop = response.stop_reason or "end_turn"
        finish_reason = "length" if raw_stop == "max_tokens" else "stop"

        return LLMResponse(
            content=content,
            finish_reason=finish_reason,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
        )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._enc.encode(text))
