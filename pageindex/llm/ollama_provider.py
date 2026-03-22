"""
ollama_provider.py — Ollama local model provider (GLM-4 Flash, Llama, Mistral, etc.).

Key design points:
  - ONE httpx.AsyncClient created at __init__ time, 180 s timeout for large models.
  - Targets the Ollama OpenAI-compatible endpoint: /v1/chat/completions.
  - GLM-4 Flash ("glm4:flash") is the primary local model (128 k context).
  - count_tokens uses character-based approximation (len // 4) — no tokenizer needed.
  - To switch to Zhipu cloud later, change provider to "openai_compatible" in config.yaml
    and set base_url to https://open.bigmodel.cn/api/paas/v4 — zero code changes.
"""
from typing import Dict, List, Optional

import httpx

from .base import BaseLLMProvider, LLMResponse, Message


class OllamaProvider(BaseLLMProvider):

    _CONTEXT_WINDOWS: Dict[str, int] = {
        # GLM-4 Flash — primary local model
        "glm4:flash":            128_000,
        "glm4":                  128_000,
        "glm-4.7-flash:latest":  128_000,
        "glm-4.7-flash":         128_000,
        # Common Ollama models
        "llama3.1":    128_000,
        "llama3.2":    128_000,
        "mistral":      32_000,
        "mistral-nemo": 128_000,
        "qwen2.5":     128_000,
        "deepseek-r1":  64_000,
        "phi4":        16_000,
    }

    _DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, model: str, base_url: Optional[str] = None):
        self.model = model
        self.context_window = self._CONTEXT_WINDOWS.get(model, 32_000)
        self._base_url = (base_url or self._DEFAULT_BASE_URL).rstrip("/")
        # Single persistent client — never recreated per call.
        # Large local models (30B+) can take 5–10 min per call on CPU.
        self._client = httpx.AsyncClient(timeout=600.0)

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        payload: Dict = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens

        url = f"{self._base_url}/v1/chat/completions"
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        content = choice["message"].get("content") or ""
        raw_finish = choice.get("finish_reason", "stop")
        finish_reason = "length" if raw_finish == "length" else "stop"

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            finish_reason=finish_reason,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )

    def count_tokens(self, text: str) -> int:
        # Character-based approximation: ~4 chars per token (works well for English + Chinese)
        if not text:
            return 0
        return len(text) // 4

    async def aclose(self) -> None:
        """Explicitly close the underlying HTTP client."""
        await self._client.aclose()
