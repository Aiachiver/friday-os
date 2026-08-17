"""
OCR via pytesseract (a wrapper around the Tesseract OCR engine). Requires
the Tesseract binary to be installed separately — see
docs/architecture/VISION_SETUP.md — since it's a native binary, not a
Python package, and pip alone can't install it.

The core function operates on a PIL Image rather than a file path so
app/vision/pdf_extractor.py can OCR a rendered PDF page in memory
without writing it to disk first.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image

from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_configured = False


def _ensure_tesseract_configured() -> None:
    """Applies TESSERACT_CMD from .env if set — needed on Windows when
    Tesseract isn't on PATH (the installer doesn't always add it).
    Idempotent; cheap to call before every OCR operation."""
    global _configured
    if _configured:
        return
    settings = get_settings()
    custom_path = settings.secrets.tesseract_cmd
    if custom_path:
        pytesseract.pytesseract.tesseract_cmd = custom_path
        log.info("Using Tesseract binary at {}", custom_path)
    _configured = True


def ocr_pil_image(image: Image.Image, lang: str = "eng") -> dict[str, Any]:
    """Core OCR call, operating entirely in memory."""
    _ensure_tesseract_configured()
    try:
        text = pytesseract.image_to_string(image, lang=lang).strip()
    except pytesseract.TesseractNotFoundError as exc:
        return {
            "success": False,
            "error": (
                "Tesseract OCR engine is not installed or not on PATH. "
                "See docs/architecture/VISION_SETUP.md for setup instructions. "
                f"({exc})"
            ),
        }
    except Exception as exc:  # noqa: BLE001 — OCR failures must not crash the caller
        log.exception("OCR failed")
        return {"success": False, "error": str(exc)}

    return {"success": True, "text": text, "char_count": len(text)}


def extract_text_from_image(path: str | Path, lang: str = "eng") -> dict[str, Any]:
    image_path = Path(path).expanduser()
    if not image_path.exists():
        return {"success": False, "error": f"Image not found: {image_path}"}

    try:
        with Image.open(image_path) as img:
            result = ocr_pil_image(img, lang=lang)
    except Exception as exc:
        log.warning("Could not open image {} for OCR: {}", image_path, exc)
        return {"success": False, "error": f"Could not open image: {exc}"}

    if result["success"]:
        result["path"] = str(image_path)
    return result
