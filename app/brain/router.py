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


_PROVIDER_REGISTRY: dict[str, dict[str, Any]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "secret_attr": "gemini_api_key",
        "default_model": "gemini-3.7-flash",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "secret_attr": "groq_api_key",
        "default_model": "openai/gpt-oss-120b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "secret_attr": "openrouter_api_key",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "secret_attr": "together_api_key",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
    "openai": {
        "base_url": None,
        "secret_attr": "openai_api_key",
        "default_model": "gpt-4o-mini",
    },
    "ollama": {
        "base_url": None,
        "secret_attr": None,
        "default_model": "llama3.2",
    },
}


class ProviderRouter:
    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            raise ValueError("No AI providers are configured.")

        self._providers = providers

    @property
    def active_providers(self) -> list[str]:
        return [provider.name for provider in self._providers]

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.6,
    ) -> LLMResponse:
        last_error: Exception | None = None

        for provider in self._providers:
            try:
                return await provider.complete(
                    messages,
                    tools=tools,
                    temperature=temperature,
                )
            except LLMProviderError as exc:
                last_error = exc
                log.warning(
                    "Provider {} failed, trying next: {}",
                    provider.name,
                    exc,
                )

        raise LLMProviderError(
            f"All {len(self._providers)} configured providers failed. "
            f"Last error: {last_error}"
        )


class NoProvidersConfiguredRouter(ProviderRouter):
    def __init__(self) -> None:
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
            "No AI providers are configured. "
            "Add an API key to .env or run Ollama."
        )


def build_provider_router() -> ProviderRouter:
    settings = get_settings()

    priority = settings.get(
        "brain.provider_priority",
        ["gemini", "groq", "openrouter", "openai", "together"],
    )

    providers: list[LLMProvider] = []

    for provider_name in priority:
        spec = _PROVIDER_REGISTRY.get(provider_name)

        if spec is None:
            log.warning(
                "Unknown provider '{}'; skipping.",
                provider_name,
            )
            continue

        if provider_name == "ollama":
            base_url = (
                f"{settings.secrets.ollama_host.rstrip('/')}/v1"
            )
            api_key = "ollama"
        else:
            secret_attr = spec["secret_attr"]
            api_key = getattr(
                settings.secrets,
                secret_attr,
                None,
            )

            if not api_key:
                log.debug(
                    "Skipping provider '{}': no API key.",
                    provider_name,
                )
                continue

            base_url = spec["base_url"]

        model = settings.get(
            f"brain.models.{provider_name}",
            spec["default_model"],
        )

        providers.append(
            OpenAICompatibleProvider(
                name=provider_name,
                model=model,
                api_key=api_key,
                base_url=base_url,
            )
        )

        log.info(
            "AI provider registered: {} ({})",
            provider_name,
            model,
        )

    if not providers:
        log.warning(
            "No AI providers configured. "
            "FRIDAY will use fast-path commands."
        )
        return NoProvidersConfiguredRouter()

    return ProviderRouter(providers)