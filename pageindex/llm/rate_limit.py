"""
rate_limit.py — Semaphore-based concurrency limiter for LLM calls.

Design
------
* RateLimitedProvider wraps any BaseLLMProvider.
* Holds an asyncio.Semaphore(concurrency) so that at most ``concurrency``
  coroutines can call complete() simultaneously.
* This prevents overwhelming Ollama (or a cloud API) when dozens of
  asyncio tasks are scheduled via asyncio.gather().
* The semaphore is created lazily on first use, not in __init__, so that
  the object can be safely created before an event loop is running
  (e.g. at module-import time or in synchronous test setUp).

Configuration (mirrors config.yaml pipeline: section)
------------------------------------------------------
concurrency : 8  — max simultaneous LLM calls
"""
import asyncio
import logging
from typing import List, Optional

from .base import BaseLLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class RateLimitedProvider(BaseLLMProvider):
    """
    Concurrency-limiting decorator for any BaseLLMProvider.

    The asyncio.Semaphore is the outermost wrapper — callers just await
    provider.complete() and the throttle is transparent.
    """

    def __init__(self, inner: BaseLLMProvider, concurrency: int = 8):
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        self._inner = inner
        self._concurrency = concurrency
        # Lazy semaphore — created inside the running event loop on first call
        self._sem: Optional[asyncio.Semaphore] = None
        # Proxy structural attributes
        self.context_window = inner.context_window
        self.model = getattr(inner, "model", "unknown")

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        sem = self._get_semaphore()
        async with sem:
            logger.debug(
                "Semaphore acquired (%d slots remaining). Calling %s.",
                self._concurrency,
                self.model,
            )
            return await self._inner.complete(messages, temperature, max_output_tokens)

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)

    @property
    def concurrency(self) -> int:
        return self._concurrency

    # ── internal ───────────────────────────────────────────────────────────────

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Return (and lazily create) the semaphore bound to the current loop."""
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._concurrency)
        return self._sem
