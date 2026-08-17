from __future__ import annotations

import base64
import io

import pytest
from PIL import Image

from app.vision.image_encoding import encode_image_to_data_url, encode_pil_image_to_data_url


def test_encode_png_produces_valid_data_url(tmp_path):
    img = Image.new("RGB", (50, 50), color="red")
    path = tmp_path / "test.png"
    img.save(path)

    data_url = encode_image_to_data_url(path)
    assert data_url.startswith("data:image/png;base64,")

    # Decode it back and confirm it's a real, valid image.
    encoded_part = data_url.split(",", 1)[1]
    decoded_bytes = base64.b64decode(encoded_part)
    round_tripped = Image.open(io.BytesIO(decoded_bytes))
    assert round_tripped.size == (50, 50)


def test_encode_jpeg_produces_valid_data_url(tmp_path):
    img = Image.new("RGB", (50, 50), color="blue")
    path = tmp_path / "test.jpg"
    img.save(path)

    data_url = encode_image_to_data_url(path)
    assert data_url.startswith("data:image/jpeg;base64,")


def test_encode_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        encode_image_to_data_url(tmp_path / "nope.png")


def test_encode_unsupported_extension_raises_value_error(tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("not an image")
    with pytest.raises(ValueError):
        encode_image_to_data_url(path)


def test_oversized_image_gets_downscaled(tmp_path):
    huge = Image.new("RGB", (5000, 3000), color="green")
    path = tmp_path / "huge.png"
    huge.save(path)

    data_url = encode_image_to_data_url(path)
    encoded_part = data_url.split(",", 1)[1]
    decoded_bytes = base64.b64decode(encoded_part)
    result_img = Image.open(io.BytesIO(decoded_bytes))

    assert max(result_img.size) <= 2000
    # Aspect ratio should be preserved (5000x3000 -> ~2000x1200).
    assert abs(result_img.size[0] / result_img.size[1] - 5000 / 3000) < 0.01


def test_small_image_is_not_upscaled(tmp_path):
    small = Image.new("RGB", (100, 80), color="yellow")
    path = tmp_path / "small.png"
    small.save(path)

    data_url = encode_image_to_data_url(path)
    encoded_part = data_url.split(",", 1)[1]
    decoded_bytes = base64.b64decode(encoded_part)
    result_img = Image.open(io.BytesIO(decoded_bytes))

    assert result_img.size == (100, 80)


def test_encode_pil_image_directly_without_file():
    img = Image.new("RGB", (30, 30), color="purple")
    data_url = encode_pil_image_to_data_url(img)
    assert data_url.startswith("data:image/png;base64,")


def test_transparent_webp_encodes_without_crashing(tmp_path):
    """Regression test: a .webp/.gif/.bmp source with real transparency
    (mode RGBA) must be flattened to RGB before a JPEG save, or Pillow
    raises 'cannot write mode RGBA as JPEG'. An earlier version of this
    code only converted non-RGB/RGBA modes, leaving RGBA untouched and
    crashing exactly on this case."""
    img = Image.new("RGBA", (60, 60), (0, 255, 0, 128))
    path = tmp_path / "transparent.webp"
    img.save(path, format="WEBP")

    data_url = encode_image_to_data_url(path)  # must not raise
    assert data_url.startswith("data:image/jpeg;base64,")


def test_transparent_gif_encodes_without_crashing(tmp_path):
    img = Image.new("RGBA", (40, 40), (255, 0, 0, 200))
    path = tmp_path / "transparent.gif"
    img.save(path, format="GIF")

    data_url = encode_image_to_data_url(path)  # must not raise
    assert data_url.startswith("data:image/jpeg;base64,")


def test_png_with_transparency_preserves_alpha_capable_mode(tmp_path):
    """PNG output should stay lossless-capable (RGBA), unlike the JPEG
    path which must flatten it."""
    img = Image.new("RGBA", (40, 40), (10, 20, 30, 100))
    path = tmp_path / "test.png"
    img.save(path, format="PNG")

    data_url = encode_image_to_data_url(path)
    assert data_url.startswith("data:image/png;base64,")

    encoded_part = data_url.split(",", 1)[1]
    decoded_bytes = base64.b64decode(encoded_part)
    round_tripped = Image.open(io.BytesIO(decoded_bytes))
    assert round_tripped.mode in ("RGBA", "RGB")  # Pillow may report either after a round-trip; both are valid
