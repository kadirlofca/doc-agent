"""
retry.py — Retry middleware with exponential back-off + full jitter.

Design
------
* RetryProvider wraps any BaseLLMProvider.
* Retries on transient *exceptions* (network errors, rate limits, timeouts).
* Does NOT retry on clean LLMResponse(finish_reason="error") — that's a
  model-level error, not a transient infrastructure failure.
* Uses full-jitter back-off: delay = uniform(0, min(max_delay, base * factor^n))
  This avoids thundering-herd when many coroutines retry simultaneously.
* Logs each retry at WARNING level with attempt number and exception class.

Configuration (mirrors config.yaml retry: section)
---------------------------------------------------
max_attempts    : 3      — total tries (1 = no retry)
base_delay      : 1.0 s  — first back-off ceiling
max_delay       : 30.0 s — hard ceiling on sleep
backoff_factor  : 2.0    — multiplier per attempt
"""
import asyncio
import logging
import random
from typing import List, Optional

from .base import BaseLLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class RetryProvider(BaseLLMProvider):
    """
    Retry decorator for any BaseLLMProvider.

    Raises the original exception after all attempts are exhausted.
    """

    def __init__(
        self,
        inner: BaseLLMProvider,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        # Proxy structural attributes
        self.context_window = inner.context_window
        self.model = getattr(inner, "model", "unknown")

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_attempts):
            try:
                return await self._inner.complete(messages, temperature, max_output_tokens)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == self._max_attempts - 1:
                    break
                delay = self._rate_limit_delay(exc) or self._jitter_delay(attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d, %s: %s). Retrying in %.1fs.",
                    attempt + 1,
                    self._max_attempts,
                    type(exc).__name__,
                    exc or "(no message)",
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "LLM call failed after %d attempts. Last error: %s: %s",
            self._max_attempts,
            type(last_exc).__name__,
            last_exc or "(no message)",
        )
        raise last_exc  # type: ignore[misc]

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)

    # ── internal ───────────────────────────────────────────────────────────────

    def _jitter_delay(self, attempt: int) -> float:
        """Full-jitter: uniform(0, min(max_delay, base * factor^attempt))."""
        ceiling = min(self._max_delay, self._base_delay * (self._backoff_factor ** attempt))
        return random.uniform(0.0, ceiling)

    @staticmethod
    def _rate_limit_delay(exc: Exception) -> Optional[float]:
        """Extract Retry-After from rate-limit exceptions (Anthropic, OpenAI SDKs)."""
        # Anthropic: RateLimitError has response.headers["retry-after"]
        # OpenAI: RateLimitError has response.headers["retry-after"]
        try:
            headers = getattr(getattr(exc, "response", None), "headers", {})
            retry_after = headers.get("retry-after")
            if retry_after:
                return min(float(retry_after) + 0.5, 120.0)  # add small buffer, cap at 2min
        except (TypeError, ValueError, AttributeError):
            pass
        # Fallback: if it looks like a rate-limit error, use a generous default
        exc_name = type(exc).__name__.lower()
        if "ratelimit" in exc_name or "429" in str(exc):
            return 15.0  # generous 15s default for rate limits
        return None
