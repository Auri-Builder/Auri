"""
agents/ai_provider.py
---------------------
Unified AI provider abstraction for Auri.

Supports four providers through a single .chat() interface:
  - Groq       (default — free tier, Llama 3.3 70B, OpenAI-compatible)
  - Claude     (Anthropic SDK — best quality)
  - OpenAI     (GPT-4o, OpenAI SDK)
  - xAI        (Grok-2, OpenAI-compatible)

Configuration
-------------
Provider and API key are loaded from ~/.auri/config.json (created by the
first-run wizard). Falls back to environment variables for dev use:

    AURI_AI_PROVIDER  = "groq" | "claude" | "openai" | "xai"
    AURI_AI_API_KEY   = "<key>"

For Groq's free tier, get an API key at: https://console.groq.com

Usage
-----
    from agents.ai_provider import get_provider
    provider = get_provider()
    response = provider.chat(
        system="You are a financial planning assistant.",
        user="Summarise this portfolio in 3 sentences.",
    )

The .chat() method returns a plain string (the assistant's reply).
All provider-specific error handling is done internally — callers receive
either a response string or an AIProviderError exception.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".auri" / "config.json"


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class AIProviderError(Exception):
    """Raised when an AI provider call fails after retries."""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class AIProvider(ABC):
    """Common interface for all AI providers."""

    @abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """
        Send a system + user message and return the assistant reply as a string.

        Parameters
        ----------
        system      : System prompt (role/context).
        user        : User message (the actual request).
        max_tokens  : Maximum tokens in the response.
        temperature : Sampling temperature (0 = deterministic, 1 = creative).

        Raises
        ------
        AIProviderError on failure.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'Groq (Llama 3.3 70B)'."""


# ---------------------------------------------------------------------------
# Groq — free tier default
# ---------------------------------------------------------------------------

class GroqProvider(AIProvider):
    """
    Groq LPU inference — free tier supports Llama 3.3 70B.
    API is OpenAI-compatible; uses the openai SDK with a custom base URL.
    Free tier: 14,400 requests/day, 6,000 tokens/minute.
    API keys: https://console.groq.com
    """

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    BASE_URL      = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model   = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return f"Groq ({self._model})"

    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise AIProviderError("openai package not installed: pip install openai") from exc

        client = OpenAI(api_key=self._api_key, base_url=self.BASE_URL)
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system",  "content": system},
                    {"role": "user",    "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"Groq call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Claude (Anthropic)
# ---------------------------------------------------------------------------

class ClaudeProvider(AIProvider):
    """
    Anthropic Claude — best quality for nuanced financial commentary.
    Requires a separate API key from console.anthropic.com (not Claude.ai subscription).
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model   = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return f"Claude ({self._model})"

    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        try:
            import anthropic  # noqa: PLC0415
        except ImportError as exc:
            raise AIProviderError("anthropic package not installed: pip install anthropic") from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        try:
            msg = client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return msg.content[0].text if msg.content else ""
        except Exception as exc:
            raise AIProviderError(f"Claude call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class OpenAIProvider(AIProvider):
    """
    OpenAI GPT — requires API key from platform.openai.com (not ChatGPT subscription).
    """

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model   = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return f"OpenAI ({self._model})"

    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise AIProviderError("openai package not installed: pip install openai") from exc

        client = OpenAI(api_key=self._api_key)
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"OpenAI call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# xAI (Grok)
# ---------------------------------------------------------------------------

class XAIProvider(AIProvider):
    """
    xAI Grok — OpenAI-compatible API at api.x.ai.
    Requires API key from console.x.ai (separate from X Premium subscription).
    """

    DEFAULT_MODEL = "grok-2-latest"
    BASE_URL      = "https://api.x.ai/v1"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model   = model or self.DEFAULT_MODEL

    @property
    def provider_name(self) -> str:
        return f"xAI ({self._model})"

    def chat(self, system: str, user: str, max_tokens: int = 1024, temperature: float = 0.3) -> str:
        try:
            from openai import OpenAI  # noqa: PLC0415
        except ImportError as exc:
            raise AIProviderError("openai package not installed: pip install openai") from exc

        client = OpenAI(api_key=self._api_key, base_url=self.BASE_URL)
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:
            raise AIProviderError(f"xAI call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load ~/.auri/config.json if it exists."""
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass
    return {}


def save_config(provider: str, api_key: str, model: str | None = None) -> None:
    """
    Persist provider + API key to ~/.auri/config.json.
    Called by the first-run wizard after the user enters their key.
    """
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = _load_config()
    cfg["ai_provider"] = provider
    cfg["ai_api_key"]  = api_key
    if model:
        cfg["ai_model"] = model
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    logger.info("ai_provider: config saved to %s", _CONFIG_PATH)


def is_configured() -> bool:
    """Return True if an AI provider has been configured."""
    cfg = _load_config()
    env_key = os.environ.get("AURI_AI_API_KEY")
    return bool(cfg.get("ai_api_key") or env_key)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "groq":   GroqProvider,
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "xai":    XAIProvider,
}

PROVIDER_LABELS = {
    "groq":   "Groq — Llama 3.3 70B (free tier available)",
    "claude": "Claude — Anthropic Sonnet (best quality)",
    "openai": "OpenAI — GPT-4o",
    "xai":    "xAI — Grok-2",
}


def get_provider(provider: str | None = None, api_key: str | None = None) -> AIProvider:
    """
    Return a configured AIProvider instance.

    Resolution order:
      1. Arguments passed directly (programmatic override)
      2. ~/.auri/config.json  (set by first-run wizard)
      3. Environment variables AURI_AI_PROVIDER / AURI_AI_API_KEY

    Default provider when none is configured: Groq.

    Raises
    ------
    AIProviderError if no API key can be found.
    """
    cfg = _load_config()

    resolved_provider = (
        provider
        or cfg.get("ai_provider")
        or os.environ.get("AURI_AI_PROVIDER", "groq")
    ).lower()

    resolved_key = (
        api_key
        or cfg.get("ai_api_key")
        or os.environ.get("AURI_AI_API_KEY")
    )

    if not resolved_key:
        raise AIProviderError(
            f"No API key found for provider '{resolved_provider}'. "
            "Configure one via the Auri settings wizard or set the "
            "AURI_AI_API_KEY environment variable."
        )

    resolved_model = cfg.get("ai_model")

    cls = _PROVIDERS.get(resolved_provider)
    if cls is None:
        raise AIProviderError(
            f"Unknown provider '{resolved_provider}'. "
            f"Available: {list(_PROVIDERS)}"
        )

    return cls(api_key=resolved_key, model=resolved_model)
