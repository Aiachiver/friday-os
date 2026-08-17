"""
Core types for the AI brain. Every provider adapter speaks these types,
not the raw SDK's types — that's what lets the router treat Gemini, Groq,
Together, OpenRouter, and Ollama interchangeably.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None  # set on role="tool" replies
    name: str | None = None  # tool name, set on role="tool" replies
    tool_calls: list[ToolCall] = field(default_factory=list)  # set on role="assistant" turns that called tools
    image_urls: list[str] = field(default_factory=list)  # data: URLs, role="user" only -- see vision/image_encoding.py


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider_name: str = ""
    model: str = ""


@dataclass(slots=True)
class ToolSpec:
    """JSON-schema tool definition, in OpenAI's function-calling shape
    (the shape every provider we use has standardized on)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

    def to_openai_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class LLMProviderError(Exception):
    """Raised by a provider adapter on any failure (network, auth, rate
    limit, malformed response). The router catches this specifically to
    decide whether to fail over to the next provider."""


class LLMProvider:
    """Base interface. Concrete providers implement `complete`."""

    name: str = "base"

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.6,
    ) -> LLMResponse:
        raise NotImplementedError
