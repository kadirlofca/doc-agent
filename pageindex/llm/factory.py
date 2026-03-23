"""
factory.py — Create and wire LLM providers with optional middleware.

Two public functions
--------------------
create_provider(llm_config)
    Low-level: returns a bare provider with no middleware.
    Tests and one-off usage call this directly.

build_provider(llm_config, cache_config, retry_config, pipeline_config)
    High-level: creates the provider then wraps it in the middleware stack:

        RateLimitedProvider          ← outermost (throttle before any work)
          └─ CachingProvider         ← skip retry + real call on cache hit
               └─ RetryProvider      ← retry transient failures
                    └─ <BaseProvider>

    Any layer is skipped when its config disables it.

build_provider_from_opt(opt)
    Convenience wrapper that reads directly from a ConfigLoader namespace
    (the object returned by ConfigLoader().load()).

Supported ``provider`` values
------------------------------
openai            — OpenAI cloud (gpt-4o, gpt-4.1, o1, …)
anthropic         — Anthropic cloud (claude-3-*, claude-sonnet-4-6, …)
ollama            — Local Ollama server (glm4:flash, llama3.1, mistral, …)
openai_compatible — Any OpenAI-compatible endpoint (Zhipu cloud, Together, vLLM, …)
gemini            — Google Gemini cloud (gemini-2.0-flash, gemini-2.5-pro, …)
"""
import os
from types import SimpleNamespace
from typing import Any, Dict, Optional

from .base import BaseLLMProvider


def build_provider(
    llm_config: Dict[str, Any],
    cache_config: Optional[Dict[str, Any]] = None,
    retry_config: Optional[Dict[str, Any]] = None,
    pipeline_config: Optional[Dict[str, Any]] = None,
) -> BaseLLMProvider:
    """
    Build a fully-wired provider with middleware stack from plain dicts.

    Middleware order (outer → inner):
      RateLimitedProvider → CachingProvider → RetryProvider → BaseProvider
    """
    provider = create_provider(llm_config)

    # 1. Retry (innermost middleware — wraps the real API call)
    if retry_config:
        attempts = int(retry_config.get("max_attempts", 1))
        if attempts > 1:
            from .retry import RetryProvider
            provider = RetryProvider(
                inner=provider,
                max_attempts=attempts,
                base_delay=float(retry_config.get("base_delay_seconds", 1.0)),
                max_delay=float(retry_config.get("max_delay_seconds", 30.0)),
                backoff_factor=float(retry_config.get("backoff_factor", 2.0)),
            )

    # 2. Cache (wraps retry so a cache hit bypasses retry overhead entirely)
    if cache_config and cache_config.get("enabled", False):
        from .cache import CachingProvider, DiskPromptCache
        disk_cache = DiskPromptCache(
            directory=str(cache_config.get("directory", ".cache/prompts")),
            ttl_seconds=int(cache_config.get("ttl_seconds", 86_400)),
        )
        provider = CachingProvider(inner=provider, cache=disk_cache)

    # 3. Rate limiter (outermost — throttles before any work is done)
    if pipeline_config:
        concurrency = int(pipeline_config.get("concurrency", 8))
        if concurrency > 0:
            from .rate_limit import RateLimitedProvider
            provider = RateLimitedProvider(inner=provider, concurrency=concurrency)

    return provider


def build_provider_from_opt(opt: SimpleNamespace) -> BaseLLMProvider:
    """
    Build provider from a ConfigLoader namespace (opt = ConfigLoader().load()).

    Reads opt.llm, opt.cache, opt.retry, opt.pipeline.
    Falls back gracefully if sections are absent.
    """
    def _ns_to_dict(ns: Any) -> Dict[str, Any]:
        if isinstance(ns, SimpleNamespace):
            return vars(ns)
        if isinstance(ns, dict):
            return ns
        return {}

    return build_provider(
        llm_config=_ns_to_dict(getattr(opt, "llm", {})),
        cache_config=_ns_to_dict(getattr(opt, "cache", {})),
        retry_config=_ns_to_dict(getattr(opt, "retry", {})),
        pipeline_config=_ns_to_dict(getattr(opt, "pipeline", {})),
    )


def create_provider(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    """
    Instantiate and return the correct BaseLLMProvider.

    Parameters
    ----------
    llm_config : dict
        Contents of the ``llm:`` section from config.yaml (already parsed).
        Required key: ``provider``.
        Other keys depend on the provider.

    Returns
    -------
    BaseLLMProvider
        A ready-to-use provider instance.
    """
    provider = llm_config.get("provider", "openai").lower()

    if provider == "openai":
        return _make_openai(llm_config)
    elif provider == "anthropic":
        return _make_anthropic(llm_config)
    elif provider == "ollama":
        return _make_ollama(llm_config)
    elif provider == "openai_compatible":
        return _make_openai_compatible(llm_config)
    elif provider == "gemini":
        return _make_gemini(llm_config)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            "Expected one of: openai, anthropic, ollama, openai_compatible, gemini."
        )


# ── private helpers ────────────────────────────────────────────────────────────

def _resolve_api_key(llm_config: Dict[str, Any], env_var: str, label: str) -> str:
    """Return API key: explicit value in config → env var → error."""
    key = llm_config.get("api_key") or os.getenv(
        llm_config.get("api_key_env", env_var)
    )
    if not key:
        raise ValueError(
            f"{label} provider requires an API key. "
            f"Set {env_var} in your environment or api_key in config.yaml."
        )
    return key


def _make_openai(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    from .openai_provider import OpenAIProvider
    model = llm_config.get("model", "gpt-4o")
    api_key = _resolve_api_key(llm_config, "OPENAI_API_KEY", "OpenAI")
    return OpenAIProvider(model=model, api_key=api_key)


def _make_anthropic(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    from .anthropic_provider import AnthropicProvider
    model = llm_config.get("model", "claude-sonnet-4-6")
    api_key = _resolve_api_key(llm_config, "ANTHROPIC_API_KEY", "Anthropic")
    return AnthropicProvider(model=model, api_key=api_key)


def _make_ollama(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    from .ollama_provider import OllamaProvider
    model = llm_config.get("model", "glm4:flash")
    base_url = llm_config.get("base_url")  # None → OllamaProvider uses localhost:11434
    return OllamaProvider(model=model, base_url=base_url)


def _make_gemini(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    from .gemini_provider import GeminiProvider
    model = llm_config.get("model", "gemini-2.0-flash-lite")
    api_key = llm_config.get("api_key") or None  # falls back to env var inside provider
    return GeminiProvider(model=model, api_key=api_key)


def _make_openai_compatible(llm_config: Dict[str, Any]) -> BaseLLMProvider:
    """
    Reuses OpenAIProvider with a custom base_url.
    Works for Zhipu cloud, Together AI, vLLM, LM Studio, etc.
    """
    import openai
    from .openai_provider import OpenAIProvider

    model = llm_config.get("model", "glm-4-flash")
    base_url = llm_config.get("base_url")
    api_key = llm_config.get("api_key") or os.getenv(
        llm_config.get("api_key_env", "OPENAI_API_KEY"), "ollama"
    )

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.model = model
    # Pull context window from OpenAIProvider table or use default
    provider.context_window = OpenAIProvider._CONTEXT_WINDOWS.get(model, 128_000)

    import tiktoken
    try:
        provider._enc = tiktoken.encoding_for_model(model)
    except KeyError:
        provider._enc = tiktoken.get_encoding(OpenAIProvider._TIKTOKEN_FALLBACK)

    # Build client with custom base_url
    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    provider._client = openai.AsyncOpenAI(**client_kwargs)

    return provider
