"""Lazy BiRefNet segmenter used by recognition workers."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_segmenter = None
_status: dict[str, Any] = {
    "enabled": False,
    "loaded": False,
    "model_id": None,
    "device": None,
    "error": None,
}


def segmenter_status() -> dict[str, Any]:
    return {
        **_status,
        "enabled": bool(settings.SEARCH_SEGMENT_ENABLED),
        "model_id": settings.SEARCH_MATTING_MODEL_ID,
    }


def get_segmenter():
    """Return a ready BiRefNet segmenter or None. Never raises to callers."""
    global _segmenter
    if not settings.SEARCH_SEGMENT_ENABLED:
        _status.update({"enabled": False, "loaded": False, "error": "segment_disabled"})
        return None
    if _segmenter is not None and getattr(_segmenter, "ready", False):
        return _segmenter
    with _lock:
        if _segmenter is not None and getattr(_segmenter, "ready", False):
            return _segmenter
        try:
            from app.ml.birefnet_segmenter import BiRefNetSegmenter

            candidate = BiRefNetSegmenter(
                model_id=settings.SEARCH_MATTING_MODEL_ID,
                device=settings.SEARCH_SEGMENT_DEVICE,
                input_size=settings.SEARCH_MATTING_INPUT_SIZE,
            )
            candidate.load()
            _segmenter = candidate
            _status.update(
                {
                    "enabled": True,
                    "loaded": True,
                    "model_id": candidate.model_id,
                    "device": str(candidate.device),
                    "error": None,
                }
            )
            return _segmenter
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialize BiRefNet: %s", exc)
            _status.update(
                {
                    "enabled": True,
                    "loaded": False,
                    "model_id": settings.SEARCH_MATTING_MODEL_ID,
                    "device": settings.SEARCH_SEGMENT_DEVICE,
                    "error": str(exc)[:300],
                }
            )
            return None


def predict_mask_with_fallback(image: Image.Image, x: float | None = None, y: float | None = None):
    """Predict a foreground mask. Retry once on CPU if device inference fails."""
    global _segmenter
    del x, y
    segmenter = get_segmenter()
    if segmenter is None:
        return None
    try:
        return segmenter.predict_mask(image)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BiRefNet failed on %s (%s); retrying on CPU", segmenter.device, exc)
        try:
            with _lock:
                segmenter.to_cpu()
                _status["device"] = str(segmenter.device)
            return segmenter.predict_mask(image)
        except Exception as retry_exc:  # noqa: BLE001
            logger.warning("BiRefNet CPU retry failed: %s", retry_exc)
            _status["error"] = str(retry_exc)[:300]
            return None
