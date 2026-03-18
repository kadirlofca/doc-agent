"""
base.py — The contract every LLM provider must fulfil.

The pipeline (Phase 3+) imports ONLY from this file.
It never imports openai, anthropic, or httpx directly.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Message:
    """A single turn in a chat conversation."""
    role: str       # "user" | "assistant" | "system"
    content: str


@dataclass
class LLMResponse:
    """
    Normalized response returned by every provider.

    finish_reason is always one of:
      "stop"   — model finished naturally
      "length" — output was cut off by token limit (caller must handle continuation)
      "error"  — provider returned an error (content will be empty string)
    """
    content: str
    finish_reason: str              # "stop" | "length" | "error"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    Subclasses: OpenAIProvider, AnthropicProvider, OllamaProvider.
    Middleware wrappers (CachingProvider, RateLimitedProvider) also subclass this.

    One instance is created at startup and shared across the entire pipeline.
    Never instantiate a provider inside a hot path (per-page, per-call).
    """

    # Maximum tokens this provider+model combination accepts as input.
    # Subclasses override this per-model in their __init__.
    context_window: int = 128_000

    @abstractmethod
    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """
        Send messages to the model and return a normalized LLMResponse.
        This is the only inference method the pipeline uses.
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using this provider's tokenizer.
        Must be a local operation — no API call allowed.
        """
        ...
