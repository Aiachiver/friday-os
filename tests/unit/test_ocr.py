"""
These tests run real OCR (actual Tesseract binary, actual pytesseract
calls) against images we generate on the fly with real, known text — not
mocked. This is genuinely testable in any environment with Tesseract
installed, unlike the voice/network-dependent phases.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from app.vision.ocr import extract_text_from_image, ocr_pil_image


def _make_text_image(text: str, size: tuple[int, int] = (500, 120)) -> Image.Image:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    draw.text((15, 40), text, fill="black")
    return img


def test_ocr_extracts_real_text_from_generated_image(tmp_path):
    img = _make_text_image("FRIDAY OS TEST")
    path = tmp_path / "test.png"
    img.save(path)

    result = extract_text_from_image(path)
    assert result["success"] is True
    assert "FRIDAY" in result["text"]


def test_ocr_pil_image_works_without_touching_disk():
    img = _make_text_image("MEMORY ONLY")
    result = ocr_pil_image(img)
    assert result["success"] is True
    assert "MEMORY" in result["text"]


def test_ocr_missing_file_reports_clean_error(tmp_path):
    result = extract_text_from_image(tmp_path / "does_not_exist.png")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_ocr_blank_image_returns_success_with_empty_text():
    blank = Image.new("RGB", (200, 100), color="white")
    result = ocr_pil_image(blank)
    assert result["success"] is True
    assert result["text"] == ""


def test_ocr_char_count_matches_text_length():
    img = _make_text_image("COUNT ME")
    result = ocr_pil_image(img)
    assert result["char_count"] == len(result["text"])
