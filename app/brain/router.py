"""
Tries providers in the priority order from config/settings.yaml
(brain.provider_priority), falling over to the next one whenever a
provider raises LLMProviderError. Only providers with a usable API key
(or Ollama, which needs none) are included at all — a provider you
haven't configured yet is skipped silently rather than attempted and
logged as a failure every single turn.
"""

from __future__ import annotations

from typing import Any

from app.brain.providers.base import (
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    Message,
    ToolSpec,
)
from app.brain.providers.openai_compatible import OpenAICompatibleProvider
from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

# provider_name -> (base_url, api_key attribute name on Secrets, default model)
_PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "secret_attr": "gemini_api_key",
        "default_model": "gemini-2.0-flash",
    },
    "openai": {
        "base_url": None,  # SDK default (api.openai.com)
        "secret_attr": "openai_api_key",
        "default_model": "gpt-4o-mini",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "secret_attr": "groq_api_key",
        "default_model": "llama-3.3-70b-versatile",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "secret_attr": "together_api_key",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "secret_attr": "openrouter_api_key",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
    },
    "ollama": {
        "base_url": None,  # filled in from settings.secrets.ollama_host + "/v1"
        "secret_attr": None,  # no key required
        "default_model": "llama3.2",
    },
}


class ProviderRouter:
    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError(
                "No AI brain providers are configured. Set at least one API key "
                "in .env (GEMINI_API_KEY, GROQ_API_KEY, etc.) or run Ollama locally."
            )
        self._providers = providers

    @property
    def active_providers(self) -> list[str]:
        return [p.name for p in self._providers]

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.6,
    ) -> LLMResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                return await provider.complete(messages, tools=tools, temperature=temperature)
            except LLMProviderError as exc:
                log.warning("Provider {} failed, trying next: {}", provider.name, exc)
                last_error = exc
                continue
        raise LLMProviderError(f"All {len(self._providers)} configured providers failed. Last error: {last_error}")


class NoProvidersConfiguredRouter(ProviderRouter):
    """
    Stand-in used when zero AI providers are configured (no API keys in
    .env and Ollama isn't reachable). Rather than crashing app startup,
    every call to complete() raises the same LLMProviderError a normal
    mid-conversation provider failure would — the orchestrator already
    has a real, tested code path for that (it speaks an honest "can't
    reach my reasoning engine" message). This is a deliberate Null
    Object, not a stub: it's the complete, correct behavior for "there
    is no brain available."
    """

    def __init__(self) -> None:  # intentionally skips ProviderRouter.__init__'s empty-list check
        self._providers = []

    @property
    def active_providers(self) -> list[str]:
        return []

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.6,
    ) -> LLMResponse:
        raise LLMProviderError(
            "No AI brain providers are configured. Set at least one API key in .env "
            "(GEMINI_API_KEY, GROQ_API_KEY, etc.) or run Ollama locally, then restart."
        )


def build_provider_router() -> ProviderRouter:
    settings = get_settings()
    priority: list[str] = settings.get(
        "brain.provider_priority", ["gemini", "groq", "openrouter", "together", "openai", "ollama"]
    )

    providers: list[LLMProvider] = []
    for provider_name in priority:
        spec = _PROVIDER_REGISTRY.get(provider_name)
        if spec is None:
            log.warning("Unknown provider '{}' in brain.provider_priority; skipping.", provider_name)
            continue

        base_url: str | None
        api_key: str | None
        if provider_name == "ollama":
            base_url = f"{settings.secrets.ollama_host.rstrip('/')}/v1"
            api_key = "ollama"
        else:
            api_key = getattr(settings.secrets, spec["secret_attr"]) if spec["secret_attr"] else None
            if not api_key:
                log.debug("Skipping provider '{}': no API key configured.", provider_name)
                continue
            base_url = spec["base_url"]

        model = settings.get(f"brain.models.{provider_name}", spec["default_model"])
        providers.append(
            OpenAICompatibleProvider(
                name=provider_name,
                model=model,
                api_key=api_key or "",
                base_url=base_url,
            )
        )
        log.info("AI brain provider registered: {} (model={})", provider_name, model)

    if not providers:
        log.warning(
            "No AI brain providers configured — FRIDAY will run with fast-path "
            "commands only until you add an API key or run Ollama. See .env.example."
        )
        return NoProvidersConfiguredRouter()

    return ProviderRouter(providers)
