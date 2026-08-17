"""
take_screenshot()'s result is mocked in these tests (rather than relying
on a real display being available in every environment this runs in) so
we can focus on verifying analyze_screen's actual logic: branching
between OCR and AI-vision modes, and failing cleanly if the screenshot
itself fails. The OCR path still runs real Tesseract against a real
generated image, since that part doesn't need a display.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.brain.providers.base import LLMResponse
from app.vision.screen_analysis import analyze_screen


class RecordingRouter:
    def __init__(self, response: LLMResponse) -> None:
        self._response = response
        self.called = False

    async def complete(self, messages, tools=None, temperature=0.6) -> LLMResponse:
        self.called = True
        return self._response


@pytest.mark.asyncio
async def test_invalid_mode_rejected_without_taking_screenshot():
    router = RecordingRouter(LLMResponse(content="unused"))
    with patch("app.vision.screen_analysis.take_screenshot") as mock_shot:
        result = await analyze_screen("not_a_real_mode", None, router)

    assert result["success"] is False
    mock_shot.assert_not_called()


@pytest.mark.asyncio
async def test_screenshot_failure_propagates_without_attempting_ocr_or_vision():
    router = RecordingRouter(LLMResponse(content="unused"))
    with patch(
        "app.vision.screen_analysis.take_screenshot",
        return_value={"success": False, "error": "no display available"},
    ):
        result = await analyze_screen("describe", None, router)

    assert result["success"] is False
    assert router.called is False


@pytest.mark.asyncio
async def test_ocr_mode_calls_ocr_not_vision(tmp_path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (300, 80), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 25), "SCREEN TEXT", fill="black")
    screenshot_path = tmp_path / "shot.png"
    img.save(screenshot_path)

    router = RecordingRouter(LLMResponse(content="should not be used"))
    with patch(
        "app.vision.screen_analysis.take_screenshot",
        return_value={"success": True, "path": str(screenshot_path)},
    ):
        result = await analyze_screen("ocr", None, router)

    assert result["success"] is True
    assert "SCREEN TEXT" in result["text"]
    assert router.called is False  # OCR mode must never touch the AI brain
    assert result["screenshot_path"] == str(screenshot_path)


@pytest.mark.asyncio
async def test_describe_mode_calls_vision_not_ocr(tmp_path):
    from PIL import Image

    img = Image.new("RGB", (100, 100), color="blue")
    screenshot_path = tmp_path / "shot.png"
    img.save(screenshot_path)

    router = RecordingRouter(LLMResponse(content="A blue screen.", provider_name="fake"))
    with patch(
        "app.vision.screen_analysis.take_screenshot",
        return_value={"success": True, "path": str(screenshot_path)},
    ):
        result = await analyze_screen("describe", "What color is this?", router)

    assert result["success"] is True
    assert result["description"] == "A blue screen."
    assert router.called is True
