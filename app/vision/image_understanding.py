"""
Image understanding ("what's in this picture", object recognition, etc.)
via the AI brain's vision-capable models — not a separate local computer-
vision model. This reuses the exact same multi-provider ProviderRouter as
regular conversation, which means it also gets automatic fallback for
free: if the first provider's model doesn't support vision (a plain-text
Groq/Ollama model, say), the request fails and the router just tries the
next provider — no vision-specific error handling needed anywhere here.
"""

from __future__ import annotations

from typing import Any

from app.brain.providers.base import LLMProviderError, Message
from app.brain.router import ProviderRouter
from app.utils.logger import get_logger
from app.vision.image_encoding import encode_image_to_data_url

log = get_logger(__name__)

_DEFAULT_QUESTION = (
    "Describe what's in this image in a few concise sentences. If there is text, "
    "readable objects, people, or anything notable, mention it plainly."
)


async def describe_image(image_path: str, question: str | None, provider_router: ProviderRouter) -> dict[str, Any]:
    try:
        data_url = encode_image_to_data_url(image_path)
    except FileNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    except (ValueError, OSError) as exc:
        return {"success": False, "error": f"Could not read image: {exc}"}

    prompt = question.strip() if question and question.strip() else _DEFAULT_QUESTION
    messages = [Message(role="user", content=prompt, image_urls=[data_url])]

    try:
        response = await provider_router.complete(messages, temperature=0.4)
    except LLMProviderError as exc:
        log.warning("describe_image failed on all providers: {}", exc)
        return {
            "success": False,
            "error": (
                "None of the configured AI providers could analyze this image — the active "
                "model may not support vision. Try a vision-capable model like gpt-4o-mini or "
                "gemini-2.0-flash (see docs/architecture/VISION_SETUP.md)."
            ),
        }

    return {"success": True, "path": image_path, "description": response.content, "provider": response.provider_name}
