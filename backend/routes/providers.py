"""
providers.py — Provider catalogue and connection endpoints.
"""
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pageindex.llm.factory import build_provider

router = APIRouter(prefix="/api/providers", tags=["providers"])

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "label": "Google Gemini", "factory": "gemini", "base_url": "",
        "key_hint": "AIza...  - aistudio.google.com",
        "models": ["gemini-2.5-flash", "gemini-2.0-flash",
                   "gemini-2.5-pro", "gemini-2.5-flash-lite",
                   "gemini-2.0-flash-lite"],
        "free": True, "chunk_budget": 16_000, "concurrency": 4, "inter_call_delay": 0.3,
    },
    "groq": {
        "label": "Groq", "factory": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "key_hint": "gsk_...  - console.groq.com",
        "models": ["llama-3.1-8b-instant", "llama-3.3-70b-versatile",
                   "gemma2-9b-it", "mixtral-8x7b-32768"],
        "free": True, "chunk_budget": 6_000, "concurrency": 1, "inter_call_delay": 3.0,
    },
    "openrouter": {
        "label": "OpenRouter", "factory": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "key_hint": "sk-or-...  - openrouter.ai",
        "models": ["meta-llama/llama-3.1-8b-instruct:free",
                   "meta-llama/llama-3.2-3b-instruct:free",
                   "google/gemma-2-9b-it:free",
                   "mistralai/mistral-7b-instruct:free",
                   "microsoft/phi-3-mini-128k-instruct:free"],
        "free": True, "chunk_budget": 8_000, "concurrency": 2, "inter_call_delay": 1.0,
    },
    "mistral": {
        "label": "Mistral AI", "factory": "openai_compatible",
        "base_url": "https://api.mistral.ai/v1",
        "key_hint": "...  - console.mistral.ai",
        "models": ["mistral-small-latest", "open-mistral-nemo",
                   "mistral-large-latest", "codestral-latest"],
        "free": True, "chunk_budget": 12_000, "concurrency": 2, "inter_call_delay": 0.5,
    },
    "openai": {
        "label": "OpenAI", "factory": "openai", "base_url": "",
        "key_hint": "sk-...  - platform.openai.com",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini"],
        "free": False, "chunk_budget": 20_000, "concurrency": 8, "inter_call_delay": 0.1,
    },
    "anthropic": {
        "label": "Anthropic", "factory": "anthropic", "base_url": "",
        "key_hint": "sk-ant-...  - console.anthropic.com",
        "models": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"],
        "free": False, "chunk_budget": 20_000, "concurrency": 2, "inter_call_delay": 2.0,
    },
}

PROVIDER_KEY_URLS = {
    "gemini": "aistudio.google.com/apikey",
    "groq": "console.groq.com/keys",
    "openrouter": "openrouter.ai/keys",
    "mistral": "console.mistral.ai/api-keys",
    "openai": "platform.openai.com/api-keys",
    "anthropic": "console.anthropic.com/settings/keys",
}


def _build_provider(provider_key: str, model: str, api_key: str = ""):
    cfg = PROVIDERS[provider_key]
    llm_cfg = {"provider": cfg["factory"], "model": model}
    api_key = api_key.strip()
    if api_key:
        llm_cfg["api_key"] = api_key
    if cfg["base_url"]:
        llm_cfg["base_url"] = cfg["base_url"]
    return build_provider(
        llm_cfg,
        retry_config={"max_attempts": 3, "base_delay_seconds": 2.0,
                      "max_delay_seconds": 60.0, "backoff_factor": 2.0},
        pipeline_config={"concurrency": cfg["concurrency"]},
    )


def friendly_error(exc: Exception, provider_key: str = "", model: str = "") -> str:
    """Map raw exceptions to user-friendly messages."""
    err = str(exc).lower()
    key_url = PROVIDER_KEY_URLS.get(provider_key, "")
    provider_label = PROVIDERS.get(provider_key, {}).get("label", provider_key)
    available_models = PROVIDERS.get(provider_key, {}).get("models", [])

    if any(k in err for k in ("authentication", "unauthorized", "invalid api key",
                               "invalid x-api-key", "api key not valid",
                               "api_key_invalid", "invalid_api_key", "401")):
        msg = f"Invalid API key for {provider_label}."
        if key_url:
            msg += f" Get a valid key at {key_url}"
        return msg

    if any(k in err for k in ("not found", "not_found", "does not exist",
                               "no longer available", "model not found")):
        msg = f"Model '{model}' is not available."
        if available_models:
            others = [m for m in available_models if m != model]
            if others:
                msg += f" Try: {', '.join(others[:3])}"
        return msg

    if any(k in err for k in ("rate limit", "ratelimit", "rate_limit",
                               "too many requests", "429", "quota",
                               "resource_exhausted", "resource exhausted")):
        return f"Rate limited by {provider_label}. Wait 30-60 seconds and try again."

    if any(k in err for k in ("timeout", "timed out", "connect", "connection",
                               "network", "unreachable")):
        return f"Connection failed to {provider_label} API. Check your internet connection."

    return "An unexpected error occurred. Please try again or switch provider/model."


class ConnectRequest(BaseModel):
    provider: str
    model: str
    api_key: str = ""


@router.get("")
async def list_providers():
    """Return the provider catalogue."""
    result = {}
    for key, cfg in PROVIDERS.items():
        result[key] = {
            "label": cfg["label"],
            "models": cfg["models"],
            "free": cfg["free"],
            "key_hint": cfg["key_hint"],
        }
    return result


@router.post("/connect")
async def connect_provider(body: ConnectRequest, request: Request):
    """Validate an API key and build a provider. Stores in server-side session."""
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")

    api_key = body.api_key.strip()
    if not api_key and body.provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""

    if not api_key:
        key_url = PROVIDER_KEY_URLS.get(body.provider, "")
        raise HTTPException(
            status_code=400,
            detail=f"API key required for {PROVIDERS[body.provider]['label']}."
                   + (f" Get one at {key_url}" if key_url else ""),
        )

    try:
        provider_obj = _build_provider(body.provider, body.model, api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=friendly_error(e, body.provider, body.model))

    # Store in server-side session
    sessions = request.app.state.sessions
    user_id = request.state.user_id
    sessions.setdefault(user_id, {})
    sessions[user_id]["provider_obj"] = provider_obj
    sessions[user_id]["provider_key"] = body.provider
    sessions[user_id]["provider_model"] = body.model

    return {
        "status": "connected",
        "provider": body.provider,
        "model": body.model,
        "label": PROVIDERS[body.provider]["label"],
    }
