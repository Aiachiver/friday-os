"""
One adapter, five providers. OpenAI, Gemini (via its OpenAI-compat beta
endpoint), Groq, Together, and OpenRouter all implement the same
chat-completions wire format; Ollama does too via its built-in
/v1/chat/completions endpoint. So this single class, configured with a
different base_url/api_key/model per provider, covers all of them —
there is no behavioral difference to abstract over.
"""

from __future__ import annotations

import json
from typing import Any

import openai

from app.brain.providers.base import (
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 30.0,
        supports_tools: bool = True,
    ) -> None:
        self.name = name
        self._model = model
        self._supports_tools = supports_tools
        # Every provider here requires *some* non-empty api_key string even
        # when the concept doesn't really apply (Ollama ignores it entirely).
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "not-required",
            base_url=base_url,
            timeout=timeout,
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.6,
    ) -> LLMResponse:
        payload_messages = [self._to_openai_message(m) for m in messages]
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": payload_messages,
            "temperature": temperature,
        }
        if tools and self._supports_tools:
            kwargs["tools"] = [t.to_openai_format() for t in tools]

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APIError as exc:
            raise LLMProviderError(f"[{self.name}] API error: {exc}") from exc
        except Exception as exc:  # network errors, timeouts, etc.
            raise LLMProviderError(f"[{self.name}] request failed: {exc}") from exc

        if not response.choices:
            raise LLMProviderError(f"[{self.name}] returned no choices")

        choice = response.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                log.warning(
                    "[{}] tool call {} had unparseable arguments: {!r}",
                    self.name,
                    tc.function.name,
                    tc.function.arguments,
                )
                arguments = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))

        return LLMResponse(
            content=choice.content or "",
            tool_calls=tool_calls,
            provider_name=self.name,
            model=self._model,
        )

    @staticmethod
    def _to_openai_message(message: Message) -> dict[str, Any]:
        if message.role == "user" and message.image_urls:
            # Vision messages use a multipart content array instead of a
            # plain string -- this is the one shape shared by every
            # provider here that supports image input (OpenAI, Gemini's
            # OpenAI-compat endpoint, and vision-capable Groq/OpenRouter
            # models). A provider/model with no vision support simply
            # errors on this payload, which the router already treats as
            # a normal failover trigger -- no separate vision-specific
            # error handling needed.
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for url in message.image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
            return {"role": message.role, "content": content}

        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
            payload["name"] = message.name
        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in message.tool_calls
            ]
        return payload
