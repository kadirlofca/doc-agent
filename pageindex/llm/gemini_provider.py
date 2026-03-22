"""
gemini_provider.py — Google Gemini provider using the google-genai SDK.

Key design points:
  - Uses google-genai (the new SDK; google-generativeai is deprecated).
  - ONE client created at __init__ time, reused for all calls.
  - Role mapping: "assistant" → "model" (Gemini API requirement).
  - System messages extracted and passed via GenerateContentConfig.
  - finish_reason normalized: "STOP" → "stop", "MAX_TOKENS" → "length".
  - count_tokens uses tiktoken cl100k_base locally — zero API calls (approximation).
  - API key: arg → GEMINI_API_KEY env → GOOGLE_API_KEY env.
"""
import os
from typing import Dict, List, Optional

import tiktoken

from .base import BaseLLMProvider, LLMResponse, Message


class GeminiProvider(BaseLLMProvider):

    _CONTEXT_WINDOWS: Dict[str, int] = {
        "gemini-2.5-flash":             1_048_576,
        "gemini-2.5-pro":               1_048_576,
        "gemini-2.5-flash-lite":        1_048_576,
        "gemini-2.0-flash":             1_048_576,
        "gemini-2.0-flash-lite":        1_048_576,
    }

    _TIKTOKEN_APPROX = "cl100k_base"

    def __init__(self, model: str, api_key: Optional[str] = None):
        from google import genai  # lazy import — optional dependency

        resolved_key = (
            api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        if not resolved_key:
            raise ValueError(
                "Gemini provider requires an API key. "
                "Set GEMINI_API_KEY (or GOOGLE_API_KEY) in your environment, "
                "or enter it in the UI."
            )

        self.model = model
        self.context_window = self._CONTEXT_WINDOWS.get(model, 1_048_576)
        self._client = genai.Client(api_key=resolved_key)
        self._enc = tiktoken.get_encoding(self._TIKTOKEN_APPROX)

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        from google.genai import types

        # Separate system messages
        system_parts = [m.content for m in messages if m.role == "system"]
        chat_messages = [m for m in messages if m.role != "system"]

        # Build contents list — Gemini roles: "user" | "model"
        contents = []
        for m in chat_messages:
            role = "model" if m.role == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=m.content)])
            )

        # Build generation config
        gen_config_kwargs = {"temperature": temperature}
        if max_output_tokens:
            gen_config_kwargs["max_output_tokens"] = max_output_tokens
        if system_parts:
            gen_config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        config = types.GenerateContentConfig(**gen_config_kwargs)

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        # Extract text
        try:
            content = response.text or ""
        except Exception:
            content = ""

        # Normalize finish reason
        try:
            raw_finish = response.candidates[0].finish_reason.name
        except Exception:
            raw_finish = "STOP"
        finish_reason = "length" if raw_finish == "MAX_TOKENS" else "stop"

        # Token usage
        try:
            input_tokens  = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count
        except Exception:
            input_tokens = output_tokens = None

        return LLMResponse(
            content=content,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._enc.encode(text))
