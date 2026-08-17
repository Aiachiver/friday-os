"""
Screen analysis: takes a screenshot and either OCRs it (fast, exact text,
good for "what does this error message say") or asks the AI brain to
describe/answer questions about it (slower, understands layout and
meaning, good for "what's open on my screen right now"). Both modes
reuse existing building blocks — Phase 3's take_screenshot() and this
phase's ocr.py / image_understanding.py — rather than duplicating
screenshot logic here.
"""

from __future__ import annotations

from typing import Any

from app.automation.desktop.screenshot import take_screenshot
from app.brain.router import ProviderRouter
from app.utils.logger import get_logger
from app.vision import ocr
from app.vision.image_understanding import describe_image

log = get_logger(__name__)


async def analyze_screen(mode: str, question: str | None, provider_router: ProviderRouter) -> dict[str, Any]:
    """
    mode: "ocr" for exact text extraction, "describe" for an AI
    description/Q&A about what's currently on screen.
    """
    if mode not in ("ocr", "describe"):
        return {"success": False, "error": f"mode must be 'ocr' or 'describe', got {mode!r}"}

    screenshot_result = take_screenshot()
    if not screenshot_result["success"]:
        return screenshot_result

    screenshot_path = screenshot_result["path"]

    if mode == "ocr":
        result = ocr.extract_text_from_image(screenshot_path)
    else:
        result = await describe_image(screenshot_path, question, provider_router)

    result["screenshot_path"] = screenshot_path
    return result
