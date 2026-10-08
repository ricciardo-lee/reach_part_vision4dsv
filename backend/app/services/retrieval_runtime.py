"""Lazy singleton for SimilarityService used by API / Celery workers."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR, settings
from app.ml.embedding import create_embedder
from app.repositories.index_loader import (
    IndexCompatibilityError,
    find_latest_index,
    load_memory_index,
    validate_index_meta,
)
from app.repositories.vector_repo import create_vector_repo
from app.services.image_preprocessing import (
    PREPROCESS_VERSION,
    WHITE_PREPROCESS_VERSION,
    ImagePreprocessor,
    PreprocessConfig,
)
from app.services.similarity import SimilarityService

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_service: SimilarityService | None = None
_init_error: str | None = None
_status: dict[str, Any] = {
    "enabled": False,
    "ready": False,
    "vector_backend": None,
    "qdrant_ok": False,
    "index_version": None,
    "embedding_model": None,
    "error": None,
}


def retrieval_status() -> dict[str, Any]:
    from app.services.segment_runtime import segmenter_status

    return {**_status, "segmenter": segmenter_status()}


def get_similarity_service() -> SimilarityService | None:
    """Return ready SimilarityService or None if retrieval is disabled / unavailable."""
    global _service, _init_error
    if not settings.RETRIEVAL_ENABLED:
        _status.update({"enabled": False, "ready": False, "error": "retrieval_disabled"})
        return None
    if _service is not None and _service.ready:
        return _service
    with _lock:
        if _service is not None and _service.ready:
            return _service
        try:
            _service = _build_service()
            _init_error = None
            _status.update(
                {
                    "enabled": True,
                    "ready": bool(_service and _service.ready),
                    "vector_backend": settings.VECTOR_BACKEND,
                    "qdrant_ok": settings.VECTOR_BACKEND.lower() == "qdrant"
                    and bool(getattr(_service.vector_repo, "ready", False)),
                    "index_version": getattr(_service, "index_version", None),
                    "embedding_model": getattr(_service.embedder, "model_id", None),
                    "error": None if (_service and _service.ready) else "not_ready",
                }
            )
            return _service if _service and _service.ready else None
        except Exception as exc:  # noqa: BLE001
            _init_error = str(exc)
            logger.exception("Failed to initialize similarity service: %s", exc)
            _status.update(
                {
                    "enabled": True,
                    "ready": False,
                    "vector_backend": settings.VECTOR_BACKEND,
                    "qdrant_ok": False,
                    "index_version": None,
                    "embedding_model": settings.resolved_embedding_model_id,
                    "error": _init_error,
                }
            )
            return None


def _resolve_configured_dir(raw_value: str) -> Path:
    raw = Path(raw_value)
    if raw.is_absolute():
        return raw
    candidates = [
        ROOT_DIR.parent / raw,
        ROOT_DIR / raw,
        Path.cwd() / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_index_dir() -> Path:
    raw = Path(settings.SEARCH_INDEX_DIR)
    if not raw.is_absolute():
        # Prefer project-root data/indexes, then backend/data/indexes
        candidates = [
            ROOT_DIR.parent / raw,
            ROOT_DIR / raw,
            Path.cwd() / raw,
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]
    return raw


def _build_service() -> SimilarityService:
    embedder = create_embedder(
        settings.EMBEDDING_BACKEND,
        model_id=settings.resolved_embedding_model_id,
    )
    embedder.load()

    preprocess_cfg = PreprocessConfig(
        target_size=settings.SEARCH_TARGET_SIZE,
        enable_foreground=settings.SEARCH_ENABLE_FOREGROUND,
        query_dual_path=settings.SEARCH_ENABLE_DUAL_PATH,
    )
    preprocessor = ImagePreprocessor(config=preprocess_cfg)

    vector_repo = create_vector_repo(
        settings.VECTOR_BACKEND,
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY or None,
    )
    index_version = settings.SEARCH_INDEX_VERSION
    index_meta: dict = {}

    if settings.VECTOR_BACKEND.lower() == "qdrant":
        vector_repo.collection = settings.QDRANT_COLLECTION
        if not getattr(vector_repo, "ready", False):
            logger.warning(
                "Qdrant collection %s missing or empty; retrieval unavailable",
                settings.QDRANT_COLLECTION,
            )
    else:
        index_root = _resolve_index_dir()
        latest = find_latest_index(
            index_root,
            embedding_backend=settings.EMBEDDING_BACKEND,
            embedding_model=settings.resolved_embedding_model_id,
            preprocess_version=PREPROCESS_VERSION,
        )
        if latest is None:
            raise RuntimeError(f"No compatible memory index under {index_root}")
        vector_repo, index_meta = load_memory_index(latest)
        validate_index_meta(
            index_meta,
            embedding_backend=settings.EMBEDDING_BACKEND,
            embedding_model=settings.resolved_embedding_model_id,
            vector_size=getattr(embedder, "vector_size", None),
        )
        index_version = index_meta.get("index_version") or index_version or latest.name

    if not index_version and settings.VECTOR_BACKEND.lower() == "qdrant":
        # Try to read index_version from a local dump meta if present
        index_root = _resolve_index_dir()
        latest_meta = index_root / "latest_meta.json"
        if latest_meta.is_file():
            import json

            meta = json.loads(latest_meta.read_text(encoding="utf-8"))
            index_version = meta.get("index_version") or index_version

    white_repo = None
    white_index_version = None
    white_dir = (settings.SEARCH_WHITE_INDEX_DIR or "").strip()
    if white_dir and settings.VECTOR_BACKEND.lower() != "qdrant":
        white_path = _resolve_configured_dir(white_dir)
        if (white_path / "vectors.npy").is_file():
            white_repo, white_meta = load_memory_index(white_path)
            validate_index_meta(
                white_meta,
                embedding_backend=settings.EMBEDDING_BACKEND,
                embedding_model=settings.resolved_embedding_model_id,
                vector_size=getattr(embedder, "vector_size", None),
                require_preprocess_version=WHITE_PREPROCESS_VERSION,
            )
            white_index_version = (
                white_meta.get("index_version") or white_path.name
            )
            logger.info("White cutout index ready: %s", white_index_version)
        else:
            logger.warning(
                "SEARCH_WHITE_INDEX_DIR=%s has no vectors.npy; foreground search uses the full index",
                white_path,
            )

    service = SimilarityService(
        embedder=embedder,
        vector_repo=vector_repo,
        preprocessor=preprocessor,
        index_version=index_version,
        white_vector_repo=white_repo,
        white_index_version=white_index_version,
        aggregate=settings.SEARCH_AGGREGATE,  # type: ignore[arg-type]
        topm=settings.SEARCH_TOPM,
        per_image_top_k=settings.SEARCH_PER_IMAGE_TOP_K,
        high_score=settings.SEARCH_HIGH_SCORE,
        medium_score=settings.SEARCH_MEDIUM_SCORE,
        min_margin=settings.SEARCH_MIN_MARGIN,
        enable_dual_path=settings.SEARCH_ENABLE_DUAL_PATH,
    )
    # Category-match thresholds live on settings; callers read them via settings.
    logger.info(
        "SimilarityService ready=%s backend=%s vector=%s index=%s",
        service.ready,
        settings.EMBEDDING_BACKEND,
        settings.VECTOR_BACKEND,
        index_version,
    )
    return service
