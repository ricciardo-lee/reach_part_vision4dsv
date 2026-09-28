"""Versioned image preprocessing shared by index, eval, and online search."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageOps

# Bump when letterbox / EXIF / gallery protocol changes.
PREPROCESS_VERSION = "gallery_full_letterbox_v1"


@dataclass
class PreprocessConfig:
    """Shared protocol for gallery indexing and query embedding."""

    version: str = PREPROCESS_VERSION
    target_size: int = 224
    min_side: int = 64
    blur_threshold: float = 20.0
    enable_foreground: bool = True
    enable_denoise: bool = False
    gallery_path: str = "full"  # gallery always indexes full letterbox
    query_dual_path: bool = True
    query_foreground_version: str = "point_sam_v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PreprocessConfig:
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ImageQuality:
    width: int
    height: int
    blur_score: float
    brightness: float
    weight: float
    warnings: list[str] = field(default_factory=list)
    usable: bool = True


@dataclass
class PreparedImage:
    original: Image.Image
    full: Image.Image
    foreground: Image.Image | None
    quality: ImageQuality
    foreground_source: str = "full_only"


def _laplacian_variance(gray: np.ndarray) -> float:
    g = gray.astype(np.float32)
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    padded = np.pad(g, 1, mode="edge")
    out = (
        kernel[0, 0] * padded[:-2, :-2]
        + kernel[0, 1] * padded[:-2, 1:-1]
        + kernel[0, 2] * padded[:-2, 2:]
        + kernel[1, 0] * padded[1:-1, :-2]
        + kernel[1, 1] * padded[1:-1, 1:-1]
        + kernel[1, 2] * padded[1:-1, 2:]
        + kernel[2, 0] * padded[2:, :-2]
        + kernel[2, 1] * padded[2:, 1:-1]
        + kernel[2, 2] * padded[2:, 2:]
    )
    return float(out.var())


def letterbox(image: Image.Image, size: int = 224, fill: int = 114) -> Image.Image:
    """Resize keeping aspect ratio, pad to square."""
    img = image.convert("RGB")
    w, h = img.size
    scale = size / max(w, h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (size, size), (fill, fill, fill))
    canvas.paste(resized, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def border_occupancy(mask: np.ndarray) -> float:
    """Share of the image rim that the mask claims. Background usually owns the rim."""
    arr = np.asarray(mask).astype(bool)
    if arr.ndim != 2 or min(arr.shape) < 2:
        return 1.0
    rim = np.concatenate([arr[0, :], arr[-1, :], arr[1:-1, 0], arr[1:-1, -1]])
    if rim.size == 0:
        return 1.0
    return float(rim.mean())


def orient_foreground_mask(mask: np.ndarray) -> np.ndarray:
    """Keep the part. A mask that hugs the frame edge is the floor or wall, so flip it."""
    arr = np.asarray(mask).astype(bool)
    if arr.ndim != 2:
        return arr
    rim = border_occupancy(arr)
    inverse = ~arr
    inverse_area = float(inverse.mean())
    if rim >= 0.55 and border_occupancy(inverse) <= 0.35 and 0.02 <= inverse_area <= 0.92:
        return inverse
    return arr


def crop_foreground_from_mask(
    image: Image.Image,
    mask: np.ndarray,
    *,
    margin_ratio: float = 0.05,
    fill: int = 255,
    min_area: float = 0.02,
    max_area: float = 0.92,
    point: tuple[float, float] | None = None,
) -> Image.Image | None:
    """Compose a white-background cutout from a boolean mask. Returns None if invalid."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    arr = np.asarray(mask).astype(bool)
    if arr.ndim != 2 or arr.shape[0] != h or arr.shape[1] != w:
        return None
    area = float(arr.mean())
    if area < min_area or area > max_area:
        return None
    if point is not None:
        px = int(round(float(np.clip(point[0], 0.0, 1.0) * (w - 1))))
        py = int(round(float(np.clip(point[1], 0.0, 1.0) * (h - 1))))
        if not bool(arr[py, px]):
            return None
    ys, xs = np.where(arr)
    if len(xs) < 100:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    mw = int((x1 - x0 + 1) * margin_ratio)
    mh = int((y1 - y0 + 1) * margin_ratio)
    x0 = max(0, x0 - mw)
    y0 = max(0, y0 - mh)
    x1 = min(w - 1, x1 + mw)
    y1 = min(h - 1, y1 + mh)
    if (x1 - x0) < w * 0.15 or (y1 - y0) < h * 0.15:
        return None
    pixels = np.asarray(rgb)
    canvas = np.full_like(pixels, fill)
    canvas[arr] = pixels[arr]
    cropped = Image.fromarray(canvas).crop((x0, y0, x1 + 1, y1 + 1))
    return cropped


def prepare_gallery_image(image: Image.Image, config: PreprocessConfig | None = None) -> Image.Image:
    """Canonical gallery path: EXIF transpose + full letterbox (no foreground)."""
    cfg = config or PreprocessConfig()
    oriented = ImageOps.exif_transpose(image).convert("RGB")
    return letterbox(oriented, size=cfg.target_size)


def prepare_query_images(
    image: Image.Image, config: PreprocessConfig | None = None
) -> PreparedImage:
    """Query path: quality gate + full letterbox + optional foreground."""
    cfg = config or PreprocessConfig()
    preprocessor = ImagePreprocessor(config=cfg)
    return preprocessor.prepare(image)


class ImagePreprocessor:
    def __init__(
        self,
        target_size: int | None = None,
        min_side: int | None = None,
        blur_threshold: float | None = None,
        enable_foreground: bool | None = None,
        enable_denoise: bool | None = None,
        config: PreprocessConfig | None = None,
    ) -> None:
        base = config or PreprocessConfig()
        self.config = PreprocessConfig(
            version=base.version,
            target_size=target_size if target_size is not None else base.target_size,
            min_side=min_side if min_side is not None else base.min_side,
            blur_threshold=blur_threshold if blur_threshold is not None else base.blur_threshold,
            enable_foreground=(
                enable_foreground if enable_foreground is not None else base.enable_foreground
            ),
            enable_denoise=enable_denoise if enable_denoise is not None else base.enable_denoise,
            gallery_path=base.gallery_path,
            query_dual_path=base.query_dual_path,
            query_foreground_version=base.query_foreground_version,
        )
        self.target_size = self.config.target_size
        self.min_side = self.config.min_side
        self.blur_threshold = self.config.blur_threshold
        self.enable_foreground = self.config.enable_foreground
        self.enable_denoise = self.config.enable_denoise

    def assess(self, image: Image.Image) -> ImageQuality:
        img = ImageOps.exif_transpose(image).convert("RGB")
        w, h = img.size
        gray = np.asarray(img.convert("L"), dtype=np.float32)
        blur = _laplacian_variance(gray)
        brightness = float(gray.mean())
        warnings: list[str] = []
        usable = True
        weight = 1.0

        if min(w, h) < self.min_side:
            warnings.append("low_resolution")
            usable = False
            weight = 0.0
        if blur < self.blur_threshold:
            warnings.append("blurry")
            weight *= 0.35
        if brightness < 35:
            warnings.append("underexposed")
            weight *= 0.6
        if brightness > 230:
            warnings.append("overexposed")
            weight *= 0.6

        if weight < 0.15 and usable:
            usable = False
        return ImageQuality(
            width=w,
            height=h,
            blur_score=blur,
            brightness=brightness,
            weight=max(0.0, min(1.0, weight)),
            warnings=warnings,
            usable=usable and weight > 0,
        )

    def prepare(
        self,
        image: Image.Image,
        focus_point: dict | tuple[float, float] | None = None,
        segmenter_predict=None,
    ) -> PreparedImage:
        oriented = ImageOps.exif_transpose(image).convert("RGB")
        quality = self.assess(oriented)
        full = letterbox(oriented, size=self.target_size)
        foreground = None
        source = "full_only"
        if self.enable_foreground:
            foreground, source = self._build_foreground(oriented, focus_point, segmenter_predict)
        return PreparedImage(
            original=oriented,
            full=full,
            foreground=foreground,
            quality=quality,
            foreground_source=source,
        )

    def _build_foreground(
        self,
        oriented: Image.Image,
        focus_point,
        segmenter_predict,
    ) -> tuple[Image.Image | None, str]:
        from app.core.config import settings

        del focus_point
        predict = segmenter_predict
        if predict is None and settings.SEARCH_SEGMENT_ENABLED:
            try:
                from app.services.segment_runtime import predict_mask_with_fallback

                predict = predict_mask_with_fallback
            except Exception:  # noqa: BLE001
                predict = None

        if predict is not None:
            try:
                mask = predict(oriented)
            except Exception:  # noqa: BLE001
                mask = None
            if mask is not None:
                mask = orient_foreground_mask(mask)
                cropped = crop_foreground_from_mask(
                    oriented,
                    mask,
                    margin_ratio=settings.SEARCH_SEGMENT_CROP_MARGIN,
                    min_area=settings.SEARCH_SEGMENT_MIN_AREA,
                    max_area=settings.SEARCH_SEGMENT_MAX_AREA,
                )
                if cropped is not None:
                    return letterbox(cropped, size=self.target_size, fill=255), "birefnet"
        return None, "full_only"

    def prepare_many(
        self,
        images: list[Image.Image],
        focus_points: list | None = None,
        segmenter_predict=None,
    ) -> list[PreparedImage]:
        points = list(focus_points or [])
        while len(points) < len(images):
            points.append(None)
        return [
            self.prepare(img, focus_point=points[i], segmenter_predict=segmenter_predict)
            for i, img in enumerate(images)
        ]

    def prepare_gallery(self, image: Image.Image) -> Image.Image:
        return prepare_gallery_image(image, self.config)
