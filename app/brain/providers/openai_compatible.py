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
        self.model = model
        self.supports_tools = supports_tools

        self.client = openai.AsyncOpenAI(
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
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._to_openai_message(message) for message in messages],
            "temperature": temperature,
        }

        if tools and self.supports_tools:
            payload["tools"] = [tool.to_openai_format() for tool in tools]

        try:
            response = await self.client.chat.completions.create(**payload)
        except openai.APIError as exc:
            raise LLMProviderError(
                f"[{self.name}] API error: {exc}"
            ) from exc
        except Exception as exc:
            raise LLMProviderError(
                f"[{self.name}] request failed: {exc}"
            ) from exc

        if not response.choices:
            raise LLMProviderError(f"[{self.name}] returned no choices")

        message = response.choices[0].message

        return LLMResponse(
            content=message.content or "",
            tool_calls=self._parse_tool_calls(message.tool_calls),
            provider_name=self.name,
            model=self.model,
        )

    def _parse_tool_calls(self, calls: Any) -> list[ToolCall]:
        tool_calls: list[ToolCall] = []

        for call in calls or []:
            arguments: dict[str, Any] = {}

            if call.function.arguments:
                try:
                    arguments = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    log.warning(
                        "[{}] Invalid tool arguments: {!r}",
                        self.name,
                        call.function.arguments,
                    )

            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=arguments,
                )
            )

        return tool_calls

    @staticmethod
    def _to_openai_message(message: Message) -> dict[str, Any]:
        if message.role == "user" and message.image_urls:
            content: list[dict[str, Any]] = []

            if message.content:
                content.append(
                    {
                        "type": "text",
                        "text": message.content,
                    }
                )

            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": url},
                }
                for url in message.image_urls
            )

            return {
                "role": "user",
                "content": content,
            }

        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }

        if message.role == "tool":
            payload.update(
                {
                    "tool_call_id": message.tool_call_id,
                    "name": message.name,
                }
            )

        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]

        return payload