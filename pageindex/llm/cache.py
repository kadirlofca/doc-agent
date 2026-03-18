"""
cache.py — Prompt-level disk cache for LLM responses.

Design
------
* DiskPromptCache: stores/retrieves LLMResponse JSON files keyed by a
  SHA-256 hash of the full call signature (model, messages, temperature,
  max_output_tokens).  Files expire after ``ttl_seconds``.
* CachingProvider: transparent decorator that wraps any BaseLLMProvider.
  Pipeline code never needs to know caching is active.

Cache file format (one .json per unique call)
---------------------------------------------
{
  "content": "...",
  "finish_reason": "stop",
  "input_tokens": 120,
  "output_tokens": 45,
  "cached_at": 1710000000.0
}
"""
import hashlib
import json
import logging
import os
import time
from typing import List, Optional

from .base import BaseLLMProvider, LLMResponse, Message

logger = logging.getLogger(__name__)


class DiskPromptCache:
    """
    SHA-256-keyed JSON file cache with TTL eviction.

    Thread/coroutine safe for reads; writes are atomic via temp-file rename.
    """

    def __init__(self, directory: str = ".cache/prompts", ttl_seconds: int = 86_400):
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        os.makedirs(directory, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────────────

    def make_key(
        self,
        model: str,
        messages: List[Message],
        temperature: float,
        max_output_tokens: Optional[int],
    ) -> str:
        """Return the hex SHA-256 key for this exact call."""
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[LLMResponse]:
        """Return cached LLMResponse if present and not expired, else None."""
        path = self._path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

        if self.ttl_seconds > 0:
            age = time.time() - data.get("cached_at", 0.0)
            if age > self.ttl_seconds:
                logger.debug("Cache expired for key %s (age=%.0fs)", key[:8], age)
                return None

        logger.debug("Cache hit for key %s", key[:8])
        return LLMResponse(
            content=data["content"],
            finish_reason=data["finish_reason"],
            input_tokens=data.get("input_tokens"),
            output_tokens=data.get("output_tokens"),
        )

    def put(self, key: str, response: LLMResponse) -> None:
        """Persist a LLMResponse to disk atomically."""
        data = {
            "content": response.content,
            "finish_reason": response.finish_reason,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cached_at": time.time(),
        }
        path = self._path(key)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
            logger.debug("Cache stored for key %s", key[:8])
        except OSError as exc:
            logger.warning("Failed to write cache entry %s: %s", key[:8], exc)
            try:
                os.remove(tmp)
            except OSError:
                pass

    def invalidate(self, key: str) -> None:
        """Remove a single cache entry."""
        try:
            os.remove(self._path(key))
        except OSError:
            pass

    def clear(self) -> int:
        """Delete all cache files. Returns count deleted."""
        count = 0
        for fname in os.listdir(self.directory):
            if fname.endswith(".json"):
                try:
                    os.remove(os.path.join(self.directory, fname))
                    count += 1
                except OSError:
                    pass
        return count

    # ── internal ───────────────────────────────────────────────────────────────

    def _path(self, key: str) -> str:
        return os.path.join(self.directory, f"{key}.json")


class CachingProvider(BaseLLMProvider):
    """
    Transparent caching wrapper around any BaseLLMProvider.

    Usage
    -----
    inner = OllamaProvider(model="glm4:flash")
    cache = DiskPromptCache(directory=".cache/prompts", ttl_seconds=86400)
    provider = CachingProvider(inner, cache)
    # provider.complete() is now cached
    """

    def __init__(self, inner: BaseLLMProvider, cache: DiskPromptCache):
        self._inner = inner
        self._cache = cache
        # Proxy structural attributes so callers can interrogate the provider
        self.context_window = inner.context_window
        self.model = getattr(inner, "model", "unknown")

    async def complete(
        self,
        messages: List[Message],
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> LLMResponse:
        key = self._cache.make_key(self.model, messages, temperature, max_output_tokens)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        response = await self._inner.complete(messages, temperature, max_output_tokens)
        # Only cache clean responses (not errors)
        if response.finish_reason != "error":
            self._cache.put(key, response)
        return response

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)
