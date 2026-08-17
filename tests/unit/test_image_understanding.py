from __future__ import annotations

import pytest
from PIL import Image

from app.brain.providers.base import LLMProviderError, LLMResponse, Message
from app.vision.image_understanding import describe_image


class RecordingRouter:
    """Captures the exact messages it was called with, so we can verify
    the image was actually encoded and attached correctly, without
    needing a real vision API call."""

    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.received_messages: list[Message] | None = None

    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        self.received_messages = messages
        return self._response


class AlwaysFailsRouter:
    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        raise LLMProviderError("no vision-capable provider available")


@pytest.mark.asyncio
async def test_describe_image_attaches_encoded_image_to_message(tmp_path):
    img = Image.new("RGB", (40, 40), color="red")
    path = tmp_path / "test.png"
    img.save(path)

    router = RecordingRouter(LLMResponse(content="A solid red square.", provider_name="fake"))
    result = await describe_image(str(path), None, router)

    assert result["success"] is True
    assert result["description"] == "A solid red square."
    assert router.received_messages is not None
    sent_message = router.received_messages[0]
    assert sent_message.role == "user"
    assert len(sent_message.image_urls) == 1
    assert sent_message.image_urls[0].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_describe_image_uses_default_prompt_when_no_question_given(tmp_path):
    img = Image.new("RGB", (40, 40), color="blue")
    path = tmp_path / "test.png"
    img.save(path)

    router = RecordingRouter(LLMResponse(content="Blue square.", provider_name="fake"))
    await describe_image(str(path), None, router)

    assert "Describe" in router.received_messages[0].content


@pytest.mark.asyncio
async def test_describe_image_uses_custom_question(tmp_path):
    img = Image.new("RGB", (40, 40), color="green")
    path = tmp_path / "test.png"
    img.save(path)

    router = RecordingRouter(LLMResponse(content="Yes, it is green.", provider_name="fake"))
    result = await describe_image(str(path), "Is this image green?", router)

    assert router.received_messages[0].content == "Is this image green?"
    assert result["description"] == "Yes, it is green."


@pytest.mark.asyncio
async def test_describe_image_missing_file_fails_cleanly_without_calling_router():
    router = RecordingRouter(LLMResponse(content="should not be reached"))
    result = await describe_image("/no/such/image.png", None, router)

    assert result["success"] is False
    assert router.received_messages is None  # never even attempted the call


@pytest.mark.asyncio
async def test_describe_image_provider_outage_gives_helpful_error(tmp_path):
    img = Image.new("RGB", (40, 40), color="yellow")
    path = tmp_path / "test.png"
    img.save(path)

    result = await describe_image(str(path), None, AlwaysFailsRouter())
    assert result["success"] is False
    assert "vision" in result["error"].lower()
