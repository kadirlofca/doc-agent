"""
openai_provider.py — OpenAI provider implementation.

Key differences from the old ChatGPT_API functions:
  - ONE AsyncOpenAI client created at __init__ time, reused forever (connection pooling).
  - context_window is set per-model so chunking respects the actual limit.
  - finish_reason is normalized to "stop" | "length".
  - count_tokens uses tiktoken locally — zero API calls.
"""
from typing import Dict, List, Optional

import openai
import tiktoken

from .base import BaseLLMProvider, LLMResponse, Message


class OpenAIProvider(BaseLLMProvider):

    _CONTEXT_WINDOWS: Dict[str, int] = {
        "gpt-4o":                128_000,
        "gpt-4o-2024-11-20":     128_000,
        "gpt-4o-mini":           128_000,
        "gpt-4.1":             1_000_000,
        "gpt-4.1-mini":        1_000_000,
        "gpt-4-turbo":           128_000,
        "gpt-4-turbo-preview":   128_000,
        "o1":                    200_000,
        "o3-mini":               200_000,
    }

    # Fallback encoding when model is not in tiktoken's model map
    _TIKTOKEN_FALLBACK = "cl100k_base"

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.context_window = self._CONTEXT_WINDOWS.get(model, 128_000)

        # Single persistent async client — created ONCE, never inside a retry loop
        self._client = openai.AsyncOpenAI(api_key=api_key)

        # Tiktoken encoder — created once, cached in instance
        try:
            self._enc = tiktoken.encoding_for_model(model)
        except KeyError:
            self._enc = tiktoken.get_encoding(self._TIKTOKEN_FALLBACK)

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs: Dict = dict(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
        )
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        return LLMResponse(
            content=choice.message.content or "",
            finish_reason="length" if choice.finish_reason == "length" else "stop",
            input_tokens=response.usage.prompt_tokens if response.usage else None,
            output_tokens=response.usage.completion_tokens if response.usage else None,
        )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._enc.encode(text))
