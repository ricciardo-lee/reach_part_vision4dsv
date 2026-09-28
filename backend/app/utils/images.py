from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Tuple

from PIL import Image, ImageOps

from app.core.constants import ALLOWED_IMAGE_CONTENT_TYPES, ALLOWED_IMAGE_EXTENSIONS
from app.core.exceptions import AppError


def validate_image_meta(filename: str, content_type: str, size: int, max_bytes: int) -> None:
    suffix = Path(filename or "").suffix.lower()
    if suffix and suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise AppError(f"不支持的图片格式: {suffix}", code="invalid_image")
    if content_type and content_type.lower() not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise AppError(f"不支持的 Content-Type: {content_type}", code="invalid_image")
    if size <= 0 or size > max_bytes:
        raise AppError("图片大小超出限制", code="invalid_image")


def open_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception as exc:  # noqa: BLE001
        raise AppError("无法解析图片文件", code="invalid_image") from exc


def compress_to_jpeg_bytes(data: bytes, max_side: int = 2048, quality: int = 90) -> Tuple[bytes, int, int]:
    image = ImageOps.exif_transpose(open_image(data)).convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue(), image.width, image.height


def to_data_url(jpeg_bytes: bytes) -> str:
    import base64

    encoded = base64.b64encode(jpeg_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def compute_phash(data: bytes) -> str:
    """Simple perceptual-ish hash using grayscale thumbnail + average hash."""
    image = open_image(data).convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(image.get_flattened_data()) if hasattr(image, "get_flattened_data") else list(image.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return hashlib.sha1(bits.encode("utf-8")).hexdigest()
