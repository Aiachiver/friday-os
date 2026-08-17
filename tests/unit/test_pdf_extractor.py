from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from app.vision.pdf_extractor import extract_images_from_pdf, extract_text_from_pdf


def _build_pdf_with_native_text(path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _build_pdf_with_image_only_page(path, tmp_path, embedded_text: str) -> None:
    """Simulates a scanned page: a PDF page with an inserted image and no
    real text layer at all."""
    img = Image.new("RGB", (600, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), embedded_text, fill="black")
    img_path = tmp_path / "scan_source.png"
    img.save(img_path)

    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(0, 0, 600, 200), filename=str(img_path))
    doc.save(str(path))
    doc.close()


def test_native_text_pdf_extracts_via_native_layer(tmp_path):
    pdf_path = tmp_path / "native.pdf"
    _build_pdf_with_native_text(pdf_path, "Real extractable text layer")

    result = extract_text_from_pdf(pdf_path)
    assert result["success"] is True
    assert result["page_count"] == 1
    assert result["pages"][0]["source"] == "native"
    assert "Real extractable text layer" in result["pages"][0]["text"]


def test_scanned_page_falls_back_to_ocr(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _build_pdf_with_image_only_page(pdf_path, tmp_path, "OCR FALLBACK WORKS")

    result = extract_text_from_pdf(pdf_path)
    assert result["success"] is True
    assert result["pages"][0]["source"] == "ocr"
    assert "OCR FALLBACK" in result["pages"][0]["text"]


def test_ocr_fallback_can_be_disabled(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _build_pdf_with_image_only_page(pdf_path, tmp_path, "SHOULD NOT BE READ")

    result = extract_text_from_pdf(pdf_path, ocr_fallback=False)
    assert result["success"] is True
    assert result["pages"][0]["source"] == "none"
    assert result["pages"][0]["text"] == ""


def test_mixed_pdf_uses_correct_source_per_page(tmp_path):
    """One native-text page, one scanned page, in the same document —
    each page should independently get the right extraction method."""
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Native page one")

    img = Image.new("RGB", (600, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), "Scanned page two", fill="black")
    img_path = tmp_path / "mixed_source.png"
    img.save(img_path)
    page2 = doc.new_page()
    page2.insert_image(fitz.Rect(0, 0, 600, 200), filename=str(img_path))

    pdf_path = tmp_path / "mixed.pdf"
    doc.save(str(pdf_path))
    doc.close()

    result = extract_text_from_pdf(pdf_path)
    assert result["page_count"] == 2
    assert result["pages"][0]["source"] == "native"
    assert result["pages"][1]["source"] == "ocr"
    assert "Native page one" in result["full_text"]
    assert "Scanned page two" in result["full_text"]


def test_missing_pdf_reports_clean_error(tmp_path):
    result = extract_text_from_pdf(tmp_path / "nope.pdf")
    assert result["success"] is False
    assert "not found" in result["error"].lower()


def test_extract_images_pulls_embedded_image(tmp_path):
    pdf_path = tmp_path / "with_image.pdf"
    _build_pdf_with_image_only_page(pdf_path, tmp_path, "irrelevant text")

    out_dir = tmp_path / "extracted"
    result = extract_images_from_pdf(pdf_path, out_dir=str(out_dir))

    assert result["success"] is True
    assert result["image_count"] == 1
    assert len(result["images"]) == 1
    assert Path(result["images"][0]).exists()


def test_extract_images_from_pdf_with_no_images_returns_empty(tmp_path):
    pdf_path = tmp_path / "text_only.pdf"
    _build_pdf_with_native_text(pdf_path, "No images here")

    result = extract_images_from_pdf(pdf_path, out_dir=str(tmp_path / "out"))
    assert result["success"] is True
    assert result["image_count"] == 0
