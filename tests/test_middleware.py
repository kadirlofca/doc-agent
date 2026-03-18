"""
test_middleware.py — Unit tests for Phase 2 middleware (no real API calls).

Covers:
  - DiskPromptCache: key stability, hit/miss, TTL expiry, atomic write
  - CachingProvider: cache hit skips inner call, cache miss stores result,
                     error responses are NOT cached
  - RetryProvider: retries on exception, exhausts and re-raises,
                   no sleep on first attempt, jitter bounds, count_tokens proxied
  - RateLimitedProvider: semaphore limits concurrency, count_tokens proxied
  - build_provider / build_provider_from_opt: correct middleware stacking
"""
import asyncio
import json
import os
import time
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pageindex.llm.base import BaseLLMProvider, LLMResponse, Message
from pageindex.llm.cache import CachingProvider, DiskPromptCache
from pageindex.llm.rate_limit import RateLimitedProvider
from pageindex.llm.retry import RetryProvider
from pageindex.llm.factory import build_provider, build_provider_from_opt


# ── Shared test helpers ────────────────────────────────────────────────────────

def _make_response(content: str = "ok", finish_reason: str = "stop") -> LLMResponse:
    return LLMResponse(content=content, finish_reason=finish_reason,
                       input_tokens=10, output_tokens=5)


def _make_inner(response: LLMResponse = None, side_effect=None) -> BaseLLMProvider:
    """Build a mock inner provider."""
    inner = MagicMock(spec=BaseLLMProvider)
    inner.context_window = 128_000
    inner.model = "mock-model"
    if side_effect:
        inner.complete = AsyncMock(side_effect=side_effect)
    else:
        inner.complete = AsyncMock(return_value=response or _make_response())
    inner.count_tokens = MagicMock(return_value=42)
    return inner


def _messages(text: str = "hello") -> List[Message]:
    return [Message(role="user", content=text)]


# ── DiskPromptCache ────────────────────────────────────────────────────────────

class TestDiskPromptCache:

    def test_key_is_deterministic(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        msgs = _messages("hi")
        k1 = cache.make_key("model", msgs, 0.0, None)
        k2 = cache.make_key("model", msgs, 0.0, None)
        assert k1 == k2

    def test_different_messages_different_keys(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        k1 = cache.make_key("model", _messages("hi"), 0.0, None)
        k2 = cache.make_key("model", _messages("bye"), 0.0, None)
        assert k1 != k2

    def test_different_models_different_keys(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        k1 = cache.make_key("gpt-4o", _messages("hi"), 0.0, None)
        k2 = cache.make_key("glm4:flash", _messages("hi"), 0.0, None)
        assert k1 != k2

    def test_different_temperature_different_keys(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        k1 = cache.make_key("model", _messages("hi"), 0.0, None)
        k2 = cache.make_key("model", _messages("hi"), 0.7, None)
        assert k1 != k2

    def test_get_returns_none_on_miss(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        assert cache.get("nonexistent" * 4) is None

    def test_put_and_get_roundtrip(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        resp = _make_response("stored content")
        key = cache.make_key("model", _messages("q"), 0.0, None)
        cache.put(key, resp)
        retrieved = cache.get(key)
        assert retrieved is not None
        assert retrieved.content == "stored content"
        assert retrieved.finish_reason == "stop"
        assert retrieved.input_tokens == 10
        assert retrieved.output_tokens == 5

    def test_ttl_expired_returns_none(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path), ttl_seconds=1)
        resp = _make_response()
        key = cache.make_key("model", _messages("q"), 0.0, None)
        cache.put(key, resp)

        # Manually backdate the cached_at timestamp
        path = cache._path(key)
        with open(path, "r") as f:
            data = json.load(f)
        data["cached_at"] = time.time() - 10  # 10 seconds old, TTL=1
        with open(path, "w") as f:
            json.dump(data, f)

        assert cache.get(key) is None

    def test_ttl_zero_means_no_expiry(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path), ttl_seconds=0)
        resp = _make_response()
        key = cache.make_key("model", _messages("q"), 0.0, None)
        cache.put(key, resp)
        assert cache.get(key) is not None

    def test_invalidate_removes_entry(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        resp = _make_response()
        key = cache.make_key("model", _messages("q"), 0.0, None)
        cache.put(key, resp)
        cache.invalidate(key)
        assert cache.get(key) is None

    def test_clear_removes_all_entries(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        for i in range(5):
            key = cache.make_key("model", _messages(f"q{i}"), 0.0, None)
            cache.put(key, _make_response())
        count = cache.clear()
        assert count == 5
        assert len(os.listdir(str(tmp_path))) == 0

    def test_corrupted_file_returns_none(self, tmp_path):
        cache = DiskPromptCache(directory=str(tmp_path))
        key = "a" * 64
        path = cache._path(key)
        with open(path, "w") as f:
            f.write("not json {{")
        assert cache.get(key) is None

    def test_atomic_write_via_tmp_file(self, tmp_path):
        """put() should NOT leave a .tmp file around."""
        cache = DiskPromptCache(directory=str(tmp_path))
        key = cache.make_key("model", _messages("q"), 0.0, None)
        cache.put(key, _make_response())
        leftover = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert leftover == []


# ── CachingProvider ────────────────────────────────────────────────────────────

class TestCachingProvider:

    @pytest.mark.asyncio
    async def test_cache_miss_calls_inner_and_stores(self, tmp_path):
        inner = _make_inner(_make_response("fresh"))
        disk = DiskPromptCache(directory=str(tmp_path))
        provider = CachingProvider(inner=inner, cache=disk)

        result = await provider.complete(_messages("hi"))
        assert result.content == "fresh"
        inner.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_inner(self, tmp_path):
        inner = _make_inner(_make_response("fresh"))
        disk = DiskPromptCache(directory=str(tmp_path))
        provider = CachingProvider(inner=inner, cache=disk)

        await provider.complete(_messages("hi"))   # miss → stores
        result = await provider.complete(_messages("hi"))  # hit → no inner call
        assert result.content == "fresh"
        assert inner.complete.await_count == 1  # only called once

    @pytest.mark.asyncio
    async def test_error_response_not_cached(self, tmp_path):
        inner = _make_inner(_make_response("", finish_reason="error"))
        disk = DiskPromptCache(directory=str(tmp_path))
        provider = CachingProvider(inner=inner, cache=disk)

        await provider.complete(_messages("hi"))
        await provider.complete(_messages("hi"))
        assert inner.complete.await_count == 2  # called both times — not cached

    def test_proxies_context_window(self, tmp_path):
        inner = _make_inner()
        inner.context_window = 64_000
        disk = DiskPromptCache(directory=str(tmp_path))
        p = CachingProvider(inner=inner, cache=disk)
        assert p.context_window == 64_000

    def test_count_tokens_delegates_to_inner(self, tmp_path):
        inner = _make_inner()
        disk = DiskPromptCache(directory=str(tmp_path))
        p = CachingProvider(inner=inner, cache=disk)
        assert p.count_tokens("hello") == 42
        inner.count_tokens.assert_called_once_with("hello")


# ── RetryProvider ──────────────────────────────────────────────────────────────

class TestRetryProvider:

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        inner = _make_inner(_make_response("ok"))
        p = RetryProvider(inner=inner, max_attempts=3)
        result = await p.complete(_messages())
        assert result.content == "ok"
        assert inner.complete.await_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_exception(self):
        inner = _make_inner(side_effect=[RuntimeError("fail"), _make_response("ok")])
        p = RetryProvider(inner=inner, max_attempts=3, base_delay=0.0)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await p.complete(_messages())
        assert result.content == "ok"
        assert inner.complete.await_count == 2

    @pytest.mark.asyncio
    async def test_exhausts_and_raises(self):
        inner = _make_inner(side_effect=RuntimeError("always fails"))
        p = RetryProvider(inner=inner, max_attempts=3, base_delay=0.0)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="always fails"):
                await p.complete(_messages())
        assert inner.complete.await_count == 3

    @pytest.mark.asyncio
    async def test_no_sleep_on_final_attempt(self):
        """asyncio.sleep should be called max_attempts-1 times, not max_attempts."""
        inner = _make_inner(side_effect=RuntimeError("fail"))
        p = RetryProvider(inner=inner, max_attempts=3, base_delay=0.0)
        sleep_mock = AsyncMock()
        with patch("asyncio.sleep", sleep_mock):
            with pytest.raises(RuntimeError):
                await p.complete(_messages())
        assert sleep_mock.await_count == 2  # 3 attempts → 2 sleeps

    def test_jitter_delay_within_bounds(self):
        p = RetryProvider(_make_inner(), max_attempts=3, base_delay=1.0,
                          max_delay=30.0, backoff_factor=2.0)
        for attempt in range(5):
            delay = p._jitter_delay(attempt)
            ceiling = min(30.0, 1.0 * (2.0 ** attempt))
            assert 0.0 <= delay <= ceiling + 1e-9  # float tolerance

    def test_invalid_max_attempts_raises(self):
        with pytest.raises(ValueError, match="max_attempts"):
            RetryProvider(_make_inner(), max_attempts=0)

    def test_proxies_context_window(self):
        inner = _make_inner()
        inner.context_window = 200_000
        p = RetryProvider(inner=inner)
        assert p.context_window == 200_000

    def test_count_tokens_delegates(self):
        inner = _make_inner()
        p = RetryProvider(inner=inner)
        assert p.count_tokens("hello") == 42
        inner.count_tokens.assert_called_once_with("hello")


# ── RateLimitedProvider ────────────────────────────────────────────────────────

class TestRateLimitedProvider:

    @pytest.mark.asyncio
    async def test_single_call_passes_through(self):
        inner = _make_inner(_make_response("x"))
        p = RateLimitedProvider(inner=inner, concurrency=4)
        result = await p.complete(_messages())
        assert result.content == "x"

    @pytest.mark.asyncio
    async def test_limits_concurrency(self):
        """Only `concurrency` calls should run simultaneously."""
        concurrent_count = 0
        max_concurrent = 0

        async def slow_complete(*args, **kwargs):
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.01)
            concurrent_count -= 1
            return _make_response()

        inner = MagicMock(spec=BaseLLMProvider)
        inner.context_window = 128_000
        inner.model = "mock"
        inner.complete = slow_complete

        concurrency = 3
        p = RateLimitedProvider(inner=inner, concurrency=concurrency)

        # Launch 10 concurrent calls
        await asyncio.gather(*[p.complete(_messages()) for _ in range(10)])
        assert max_concurrent <= concurrency

    def test_invalid_concurrency_raises(self):
        with pytest.raises(ValueError, match="concurrency"):
            RateLimitedProvider(_make_inner(), concurrency=0)

    def test_proxies_context_window(self):
        inner = _make_inner()
        inner.context_window = 32_000
        p = RateLimitedProvider(inner=inner, concurrency=4)
        assert p.context_window == 32_000

    def test_count_tokens_delegates(self):
        inner = _make_inner()
        p = RateLimitedProvider(inner=inner, concurrency=4)
        assert p.count_tokens("hi") == 42

    def test_concurrency_property(self):
        inner = _make_inner()
        p = RateLimitedProvider(inner=inner, concurrency=5)
        assert p.concurrency == 5


# ── build_provider middleware stacking ────────────────────────────────────────

class TestBuildProvider:

    def test_bare_provider_no_middleware(self):
        from pageindex.llm.openai_provider import OpenAIProvider
        p = build_provider(
            llm_config={"provider": "openai", "model": "gpt-4o", "api_key": "sk-fake"},
        )
        assert isinstance(p, OpenAIProvider)

    def test_retry_wraps_provider(self):
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            retry_config={"max_attempts": 3},
        )
        assert isinstance(p, RetryProvider)
        assert p._max_attempts == 3

    def test_retry_with_max_attempts_1_no_wrapper(self):
        from pageindex.llm.ollama_provider import OllamaProvider
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            retry_config={"max_attempts": 1},
        )
        assert isinstance(p, OllamaProvider)

    def test_cache_wraps_provider(self, tmp_path):
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            cache_config={"enabled": True, "directory": str(tmp_path), "ttl_seconds": 3600},
        )
        assert isinstance(p, CachingProvider)

    def test_cache_disabled_no_wrapper(self):
        from pageindex.llm.ollama_provider import OllamaProvider
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            cache_config={"enabled": False},
        )
        assert isinstance(p, OllamaProvider)

    def test_rate_limit_wraps_provider(self):
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            pipeline_config={"concurrency": 4},
        )
        assert isinstance(p, RateLimitedProvider)
        assert p.concurrency == 4

    def test_full_stack_order(self, tmp_path):
        """RateLimited → CachingProvider → RetryProvider → OllamaProvider."""
        p = build_provider(
            llm_config={"provider": "ollama", "model": "glm4:flash"},
            cache_config={"enabled": True, "directory": str(tmp_path)},
            retry_config={"max_attempts": 2},
            pipeline_config={"concurrency": 4},
        )
        assert isinstance(p, RateLimitedProvider)
        assert isinstance(p._inner, CachingProvider)
        assert isinstance(p._inner._inner, RetryProvider)


class TestBuildProviderFromOpt:

    def test_reads_from_config_namespace(self):
        from pageindex.utils import ConfigLoader
        opt = ConfigLoader().load()
        # Default config: ollama + no cache + retry.max_attempts=3 + pipeline.concurrency=8
        p = build_provider_from_opt(opt)
        # Should be RateLimitedProvider (concurrency=8 in default config)
        assert isinstance(p, RateLimitedProvider)

    def test_missing_sections_do_not_crash(self):
        opt = SimpleNamespace()  # no llm/cache/retry/pipeline attributes
        # Should fall back to defaults and not raise
        # (provider=openai with no key will raise — so patch create_provider)
        from pageindex.llm import ollama_provider
        with patch("pageindex.llm.factory.create_provider") as mock_create:
            mock_inner = _make_inner()
            mock_create.return_value = mock_inner
            p = build_provider_from_opt(opt)
        assert p is not None
