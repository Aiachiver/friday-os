"""
Encodes local image files as base64 data URLs for vision-capable LLM
calls — the one shape every provider we support accepts for image input
(see app/brain/providers/openai_compatible.py). Kept as a single small
module because every vision entry point (describe_image, screen
analysis, PDF page rendering) needs this exact same encoding step.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

from app.utils.logger import get_logger

log = get_logger(__name__)

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}

# Most vision APIs cap accepted image dimensions (and billing scales with
# resolution) well below what a 4K screenshot produces. Downscaling large
# images before encoding avoids provider-side rejections and keeps base64
# payloads (and token costs) reasonable, at no meaningful cost to what a
# vision model can actually read from the image.
_MAX_DIMENSION = 2000


def encode_image_to_data_url(path: str | Path) -> str:
    """Reads an image file, downscales it if oversized, and returns a
    `data:image/...;base64,...` URL ready to hand to a vision-capable
    provider. Raises FileNotFoundError / PIL exceptions directly rather
    than swallowing them into a result dict — callers (image_understanding,
    screen_analysis) are responsible for the user-facing error shape,
    since this is a low-level building block used by several of them."""
    image_path = Path(path).expanduser()
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    suffix = image_path.suffix.lower()
    mime_type = _MIME_TYPES.get(suffix)
    if mime_type is None:
        raise ValueError(f"Unsupported image type '{suffix}'. Supported: {sorted(_MIME_TYPES)}")

    img: Image.Image
    with Image.open(image_path) as img:
        if max(img.size) > _MAX_DIMENSION:
            img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.Resampling.LANCZOS)
            log.debug("Downscaled {} to {} before encoding for vision API", image_path, img.size)

        save_format = "PNG" if mime_type == "image/png" else "JPEG"

        # JPEG has no alpha channel — a .webp/.gif/.bmp source with
        # transparency (mode RGBA or P) must be flattened to RGB before a
        # JPEG save, or Pillow raises "cannot write mode RGBA as JPEG".
        # PNG supports RGBA natively, so only convert there if needed for
        # some other unusual mode (e.g. CMYK, "1", "L" are all fine to
        # convert to a consistent RGBA for PNG output).
        if save_format == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif save_format == "PNG" and img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGBA")

        buffer = io.BytesIO()
        img.save(buffer, format=save_format)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    effective_mime = "image/png" if save_format == "PNG" else "image/jpeg"
    return f"data:{effective_mime};base64,{encoded}"


def encode_pil_image_to_data_url(image: Image.Image) -> str:
    """Same encoding, for an already-in-memory PIL image (e.g. a
    freshly-rendered PDF page or screenshot) that never touched disk."""
    buffer = io.BytesIO()
    rgb_image = image.convert("RGB") if image.mode not in ("RGB",) else image
    if max(rgb_image.size) > _MAX_DIMENSION:
        rgb_image.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.Resampling.LANCZOS)
    rgb_image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"
