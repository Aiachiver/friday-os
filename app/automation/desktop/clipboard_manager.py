"""Clipboard read/write. pyperclip works cross-platform (Windows natively,
Linux via xclip/xsel, macOS natively) — real functionality on any dev
machine, not just Windows, unlike most of system_control.py."""

from __future__ import annotations

from typing import Any

import pyperclip

from app.utils.logger import get_logger

log = get_logger(__name__)


def get_clipboard_text() -> dict[str, Any]:
    try:
        text = pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        log.warning("Clipboard read failed: {}", exc)
        return {"success": False, "error": str(exc)}
    return {"success": True, "text": text}


def set_clipboard_text(text: str) -> dict[str, Any]:
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        log.warning("Clipboard write failed: {}", exc)
        return {"success": False, "error": str(exc)}
    log.info("Copied {} characters to clipboard.", len(text))
    return {"success": True}
