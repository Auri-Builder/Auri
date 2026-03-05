"""
ORI_IA LLM Adapter
===================
Thin abstraction over local (Ollama) and cloud (Anthropic / OpenAI) providers.

Design principles
-----------------
  - Local adapter uses only stdlib (urllib.request) — no extra dependencies.
  - Cloud adapters use lazy imports so missing packages fail at call time, not
    at import time.  Clear error messages tell the user what to install.
  - API keys are read from environment variables only — never from config files.
  - Each adapter exposes a ``provider_label`` attribute for display / logging.

Configuration  (llm_config.yaml at repo root, gitignored)
----------------------------------------------------------
provider: local          # default — no outbound network calls

local:
  base_url: http://localhost:11434   # Ollama default
  model: llama3.2

cloud:
  provider: anthropic    # or: openai, xai
  model: claude-haiku-4-5-20251001
  # API key env vars:
  #   anthropic → ANTHROPIC_API_KEY
  #   openai    → OPENAI_API_KEY
  #   xai       → XAI_API_KEY
  # Never store API keys in config files.
"""

import json as _json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class LLMAdapter(ABC):
    provider_label: str = "unknown"

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Send prompt to the LLM and return the response text."""


# ---------------------------------------------------------------------------
# Local — Ollama
# ---------------------------------------------------------------------------

class LocalLLMAdapter(LLMAdapter):
    """
    Calls Ollama running locally (http://localhost:11434 by default).
    No data leaves the machine.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_label = f"local/{model}"

    def generate(self, prompt: str) -> str:
        payload = _json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False}
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = _json.loads(resp.read())
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url} — is it running?\n"
                f"Start with:  ollama serve\n"
                f"Error: {exc}"
            ) from exc

        return data.get("response", "").strip()


# ---------------------------------------------------------------------------
# Cloud — Anthropic
# ---------------------------------------------------------------------------

class CloudAnthropicAdapter(LLMAdapter):
    """
    Calls the Anthropic Claude API.
    Requires:  pip install anthropic
    Requires:  ANTHROPIC_API_KEY environment variable set.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self.provider_label = f"cloud/anthropic/{model}"
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set.\n"
                "Export it before starting the app:  export ANTHROPIC_API_KEY=sk-..."
            )
        self._api_key = api_key

    def generate(self, prompt: str) -> str:
        try:
            import anthropic  # lazy import — fails cleanly if not installed
        except ImportError as exc:
            raise ImportError(
                "Anthropic SDK not installed.  Run:  pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self._api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Cloud — OpenAI
# ---------------------------------------------------------------------------

class CloudOpenAIAdapter(LLMAdapter):
    """
    Calls any OpenAI-compatible API (OpenAI, xAI/Grok, etc.).
    Requires:  pip install openai
    Requires:  the appropriate API key environment variable set.

    Args:
        model:       Model name (e.g. "gpt-4o-mini", "grok-3-mini").
        base_url:    Override the API base URL (e.g. "https://api.x.ai/v1").
                     None uses the OpenAI SDK default (api.openai.com).
        api_key_env: Name of the environment variable holding the API key.
                     Defaults to "OPENAI_API_KEY".
        label:       Provider label prefix for logging (e.g. "openai", "xai").
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        label: str = "openai",
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.provider_label = f"cloud/{label}/{model}"
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(
                f"{api_key_env} environment variable is not set.\n"
                f"Export it before starting the app:  export {api_key_env}=..."
            )
        self._api_key = api_key

    def generate(self, prompt: str) -> str:
        try:
            import openai  # lazy import
        except ImportError as exc:
            raise ImportError(
                "OpenAI SDK not installed.  Run:  pip install openai"
            ) from exc

        kwargs = {"api_key": self._api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        client = openai.OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_adapter(config: Optional[dict] = None) -> LLMAdapter:
    """
    Build an LLMAdapter from a config dict (e.g. parsed from llm_config.yaml).

    Returns a LocalLLMAdapter by default (provider: local).

    Raises:
        ValueError: if config specifies an unrecognised provider name.
    """
    if config is None:
        config = {}

    provider = config.get("provider", "local")

    if provider == "local":
        local_cfg = config.get("local") or {}
        return LocalLLMAdapter(
            base_url=local_cfg.get("base_url", "http://localhost:11434"),
            model=local_cfg.get("model", "llama3.2"),
        )

    if provider == "cloud":
        cloud_cfg = config.get("cloud") or {}
        cloud_provider = cloud_cfg.get("provider", "anthropic")

        if cloud_provider == "anthropic":
            return CloudAnthropicAdapter(
                model=cloud_cfg.get("model", "claude-haiku-4-5-20251001"),
            )
        if cloud_provider == "openai":
            return CloudOpenAIAdapter(
                model=cloud_cfg.get("model", "gpt-4o-mini"),
            )
        if cloud_provider == "xai":
            return CloudOpenAIAdapter(
                model=cloud_cfg.get("model", "grok-3-mini"),
                base_url="https://api.x.ai/v1",
                api_key_env="XAI_API_KEY",
                label="xai",
            )
        raise ValueError(f"Unknown cloud provider: {cloud_provider!r}")

    raise ValueError(f"Unknown LLM provider: {provider!r}")
