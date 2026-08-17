"""
Screenshot capture via mss — chosen over Pillow's ImageGrab because mss
works identically on Windows, macOS, and Linux with no extra system
dependencies. It still needs a real display to capture, though (a
headless Linux CI/sandbox with no X server will get "Cannot connect to
display" from mss itself, not from this module) — the unit tests for
this module mock mss rather than calling it for real, same as any other
capability this project can't exercise against real hardware in CI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import mss
import mss.tools

from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)


def take_screenshot(save_dir: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    target_dir = Path(save_dir) if save_dir else settings.user_data_root / "data" / "user_files" / "screenshots"
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    out_path = target_dir / filename

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # index 0 = full virtual screen (all monitors combined)
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(out_path))
    except Exception as exc:
        log.exception("take_screenshot failed")
        return {"success": False, "error": str(exc)}

    log.info("Screenshot saved to {}", out_path)
    return {"success": True, "path": str(out_path)}
