"""
PDF text and image extraction via PyMuPDF (fitz) — chosen over
pdf2image/poppler because it ships a self-contained wheel with no system
binary dependency (poppler would be one more thing to install on
Windows), and it can both extract embedded text AND rasterize pages for
OCR from the same library.

Text extraction is hybrid: PyMuPDF's native text layer is used first
(fast, exact, works for any PDF with a real text layer) and OCR is used
per-page only as a fallback for pages that have no extractable text
(i.e. scanned/image-only pages) — this avoids OCR's speed and accuracy
cost on the common case of a normal, non-scanned PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.utils.logger import get_logger
from app.vision.ocr import ocr_pil_image

log = get_logger(__name__)

_RENDER_DPI = 200  # good balance of OCR accuracy vs. speed/memory for a full page


def extract_text_from_pdf(path: str | Path, ocr_fallback: bool = True) -> dict[str, Any]:
    """Returns per-page text plus a flag on each page for whether it came
    from the native text layer or OCR — useful for the caller (or the AI
    brain relaying results) to know how much to trust a given page."""
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        return {"success": False, "error": f"PDF not found: {pdf_path}"}

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {"success": False, "error": f"Could not open PDF: {exc}"}

    pages: list[dict[str, Any]] = []
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            native_text = page.get_text().strip()

            if native_text:
                pages.append({"page": page_index + 1, "text": native_text, "source": "native"})
                continue

            if not ocr_fallback:
                pages.append({"page": page_index + 1, "text": "", "source": "none"})
                continue

            pixmap = page.get_pixmap(dpi=_RENDER_DPI)
            pil_image = pixmap.pil_image()
            ocr_result = ocr_pil_image(pil_image)
            if ocr_result["success"]:
                pages.append({"page": page_index + 1, "text": ocr_result["text"], "source": "ocr"})
            else:
                pages.append({"page": page_index + 1, "text": "", "source": "ocr_failed", "error": ocr_result["error"]})
    finally:
        doc.close()

    full_text = "\n\n".join(p["text"] for p in pages if p["text"])
    return {
        "success": True,
        "path": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "full_text": full_text,
    }


def extract_images_from_pdf(path: str | Path, out_dir: str | None = None) -> dict[str, Any]:
    """Extracts embedded raster images (photos/figures) from a PDF, as
    opposed to rendering whole pages — these are the actual image XObjects
    in the PDF, saved at their original resolution."""
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        return {"success": False, "error": f"PDF not found: {pdf_path}"}

    target_dir = Path(out_dir) if out_dir else pdf_path.parent / f"{pdf_path.stem}_images"
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        return {"success": False, "error": f"Could not open PDF: {exc}"}

    saved_paths: list[str] = []
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                xref = image_info[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception as exc:
                    log.warning("Could not extract image xref {} on page {}: {}", xref, page_index + 1, exc)
                    continue

                ext = base_image.get("ext", "png")
                out_path = target_dir / f"page{page_index + 1}_img{image_index}.{ext}"
                out_path.write_bytes(base_image["image"])
                saved_paths.append(str(out_path))
    finally:
        doc.close()

    return {"success": True, "path": str(pdf_path), "image_count": len(saved_paths), "images": saved_paths}
