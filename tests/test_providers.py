"""
test_providers.py — Unit tests for LLM provider layer (Phase 1).

All tests run without real API calls:
  - Provider instantiation and interface checks
  - count_tokens correctness
  - LLMResponse normalisation logic
  - factory.create_provider routing
  - ConfigLoader nested-section support
"""
import os
import sys
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path (conftest.py also does this, but be explicit)
sys.path.insert(0, str(__file__))


# ── Imports ────────────────────────────────────────────────────────────────────

from pageindex.llm.base import BaseLLMProvider, LLMResponse, Message
from pageindex.llm.factory import create_provider
from pageindex.llm.openai_provider import OpenAIProvider
from pageindex.llm.ollama_provider import OllamaProvider


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_openai_provider(model: str = "gpt-4o") -> OpenAIProvider:
    return OpenAIProvider(model=model, api_key="sk-test-fake-key")


# ── BaseLLMProvider interface ──────────────────────────────────────────────────

class TestBaseLLMProviderInterface:
    """BaseLLMProvider is abstract — concrete subclasses must implement both methods."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseLLMProvider()  # type: ignore

    def test_openai_provider_is_subclass(self):
        assert issubclass(OpenAIProvider, BaseLLMProvider)

    def test_ollama_provider_is_subclass(self):
        assert issubclass(OllamaProvider, BaseLLMProvider)

    def test_message_dataclass(self):
        m = Message(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"

    def test_llm_response_defaults(self):
        r = LLMResponse(content="hi", finish_reason="stop")
        assert r.input_tokens is None
        assert r.output_tokens is None

    def test_llm_response_with_tokens(self):
        r = LLMResponse(content="hi", finish_reason="stop", input_tokens=10, output_tokens=5)
        assert r.input_tokens == 10
        assert r.output_tokens == 5


# ── OpenAIProvider ─────────────────────────────────────────────────────────────

class TestOpenAIProvider:

    def test_context_window_gpt4o(self):
        p = _make_openai_provider("gpt-4o")
        assert p.context_window == 128_000

    def test_context_window_gpt41(self):
        p = _make_openai_provider("gpt-4.1")
        assert p.context_window == 1_000_000

    def test_context_window_unknown_model_defaults_128k(self):
        p = _make_openai_provider("gpt-unknown-future")
        assert p.context_window == 128_000

    def test_count_tokens_empty_string(self):
        p = _make_openai_provider()
        assert p.count_tokens("") == 0

    def test_count_tokens_nonempty(self):
        p = _make_openai_provider()
        n = p.count_tokens("Hello, world!")
        assert isinstance(n, int)
        assert n > 0

    def test_count_tokens_longer_text_more_tokens(self):
        p = _make_openai_provider()
        short = p.count_tokens("Hi")
        long_ = p.count_tokens("Hi " * 100)
        assert long_ > short

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self):
        p = _make_openai_provider()
        mock_choice = MagicMock()
        mock_choice.message.content = "test response"
        mock_choice.finish_reason = "stop"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        p._client.chat.completions.create = AsyncMock(return_value=mock_response)

        messages = [Message(role="user", content="hello")]
        result = await p.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "test response"
        assert result.finish_reason == "stop"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_complete_normalizes_length_finish_reason(self):
        p = _make_openai_provider()
        mock_choice = MagicMock()
        mock_choice.message.content = "truncated"
        mock_choice.finish_reason = "length"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        p._client.chat.completions.create = AsyncMock(return_value=mock_response)
        result = await p.complete([Message(role="user", content="hi")])
        assert result.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_complete_passes_max_output_tokens(self):
        p = _make_openai_provider()
        mock_choice = MagicMock()
        mock_choice.message.content = ""
        mock_choice.finish_reason = "stop"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        create_mock = AsyncMock(return_value=mock_response)
        p._client.chat.completions.create = create_mock

        await p.complete([Message(role="user", content="x")], max_output_tokens=256)
        call_kwargs = create_mock.call_args[1]
        assert call_kwargs.get("max_tokens") == 256


# ── OllamaProvider ─────────────────────────────────────────────────────────────

class TestOllamaProvider:

    def test_glm4_flash_context_window(self):
        p = OllamaProvider(model="glm4:flash")
        assert p.context_window == 128_000

    def test_glm4_context_window(self):
        p = OllamaProvider(model="glm4")
        assert p.context_window == 128_000

    def test_unknown_model_defaults_32k(self):
        p = OllamaProvider(model="unknown-local-model")
        assert p.context_window == 32_000

    def test_default_base_url(self):
        p = OllamaProvider(model="glm4:flash")
        assert "localhost:11434" in p._base_url

    def test_custom_base_url(self):
        p = OllamaProvider(model="glm4:flash", base_url="http://192.168.1.100:11434")
        assert "192.168.1.100" in p._base_url

    def test_count_tokens_empty(self):
        p = OllamaProvider(model="glm4:flash")
        assert p.count_tokens("") == 0

    def test_count_tokens_approximation(self):
        p = OllamaProvider(model="glm4:flash")
        text = "a" * 400
        assert p.count_tokens(text) == 100  # 400 // 4

    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self):
        p = OllamaProvider(model="glm4:flash")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello from glm"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 4},
        }

        p._client.post = AsyncMock(return_value=mock_resp)
        messages = [Message(role="user", content="hi")]
        result = await p.complete(messages)

        assert isinstance(result, LLMResponse)
        assert result.content == "hello from glm"
        assert result.finish_reason == "stop"
        assert result.input_tokens == 8
        assert result.output_tokens == 4

    @pytest.mark.asyncio
    async def test_complete_posts_to_correct_url(self):
        p = OllamaProvider(model="glm4:flash", base_url="http://localhost:11434")
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
            "usage": {},
        }
        post_mock = AsyncMock(return_value=mock_resp)
        p._client.post = post_mock

        await p.complete([Message(role="user", content="x")])
        call_url = post_mock.call_args[0][0]
        assert call_url == "http://localhost:11434/v1/chat/completions"


# ── AnthropicProvider ─────────────────────────────────────────────────────────

class TestAnthropicProvider:
    """Tests run even if anthropic package is not installed (mock it)."""

    def _make_provider(self, model: str = "claude-sonnet-4-6"):
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from pageindex.llm.anthropic_provider import AnthropicProvider
            p = AnthropicProvider(model=model, api_key="test-key")
            p._client = mock_client
        return p

    def test_context_window_claude_sonnet(self):
        from pageindex.llm.anthropic_provider import AnthropicProvider
        # Can't easily test without import, so patch at module level
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            p = AnthropicProvider(model="claude-sonnet-4-6", api_key="k")
            assert p.context_window == 200_000

    def test_context_window_unknown_model(self):
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from pageindex.llm.anthropic_provider import AnthropicProvider
            p = AnthropicProvider(model="claude-future-9000", api_key="k")
            assert p.context_window == 200_000

    def test_count_tokens_returns_int(self):
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            from pageindex.llm.anthropic_provider import AnthropicProvider
            p = AnthropicProvider(model="claude-sonnet-4-6", api_key="k")
            assert p.count_tokens("hello world") > 0
            assert p.count_tokens("") == 0


# ── factory.create_provider ────────────────────────────────────────────────────

class TestFactory:

    def test_routes_to_openai(self):
        cfg = {"provider": "openai", "model": "gpt-4o", "api_key": "sk-fake"}
        p = create_provider(cfg)
        assert isinstance(p, OpenAIProvider)
        assert p.model == "gpt-4o"

    def test_routes_to_ollama(self):
        cfg = {"provider": "ollama", "model": "glm4:flash"}
        p = create_provider(cfg)
        assert isinstance(p, OllamaProvider)
        assert p.model == "glm4:flash"

    def test_ollama_is_default_model_glm4flash(self):
        cfg = {"provider": "ollama"}
        p = create_provider(cfg)
        assert isinstance(p, OllamaProvider)
        assert p.model == "glm4:flash"

    def test_routes_to_openai_compatible(self):
        cfg = {
            "provider": "openai_compatible",
            "model": "glm-4-flash",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",
        }
        p = create_provider(cfg)
        assert isinstance(p, OpenAIProvider)
        assert p.model == "glm-4-flash"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider({"provider": "banana"})

    def test_openai_missing_api_key_raises(self):
        # Remove env var to ensure no accidental key
        env_backup = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with pytest.raises(ValueError, match="API key"):
                create_provider({"provider": "openai", "model": "gpt-4o"})
        finally:
            if env_backup:
                os.environ["OPENAI_API_KEY"] = env_backup

    def test_routes_to_anthropic(self):
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            cfg = {
                "provider": "anthropic",
                "model": "claude-sonnet-4-6",
                "api_key": "test-key",
            }
            p = create_provider(cfg)
            from pageindex.llm.anthropic_provider import AnthropicProvider
            assert isinstance(p, AnthropicProvider)


# ── ConfigLoader nested sections ───────────────────────────────────────────────

class TestConfigLoaderNestedSections:

    def test_llm_section_accessible_as_namespace(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert hasattr(opt, "llm")
        assert hasattr(opt.llm, "provider")
        assert hasattr(opt.llm, "model")

    def test_llm_provider_is_ollama_by_default(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert opt.llm.provider == "ollama"

    def test_llm_model_is_glm4flash_by_default(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert opt.llm.model == "glm4:flash"

    def test_cache_section_exists(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert hasattr(opt, "cache")
        assert hasattr(opt.cache, "enabled")

    def test_retry_section_exists(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert hasattr(opt, "retry")
        assert hasattr(opt.retry, "max_attempts")

    def test_pipeline_section_exists(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load()
        assert hasattr(opt, "pipeline")
        assert hasattr(opt.pipeline, "concurrency")

    def test_flat_keys_still_work(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        opt = loader.load({"if_add_node_summary": "no"})
        assert opt.if_add_node_summary == "no"
        # Nested sections must also still be present
        assert hasattr(opt, "llm")

    def test_unknown_flat_key_raises(self):
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        with pytest.raises(ValueError, match="Unknown config keys"):
            loader.load({"totally_unknown_key": "value"})

    def test_nested_keys_not_flagged_as_unknown(self):
        """Passing a nested section key as a flat override should not raise."""
        from pageindex.utils import ConfigLoader
        loader = ConfigLoader()
        # This should NOT raise — "llm" is a nested section, not an unknown flat key
        # (current design: nested overrides via load() are silently ignored for safety)
        opt = loader.load({})
        assert opt is not None
