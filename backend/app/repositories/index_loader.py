"""Load a memory index dump into an InMemoryVectorRepo with compatibility checks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.repositories.vector_repo import InMemoryVectorRepo
from app.services.image_preprocessing import PREPROCESS_VERSION


class IndexCompatibilityError(ValueError):
    """Raised when loaded index does not match configured embedder/preprocess."""


def load_memory_index(index_dir: Path) -> tuple[InMemoryVectorRepo, dict]:
    index_dir = Path(index_dir)
    meta_path = index_dir / "index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    vectors = np.load(index_dir / "vectors.npy")
    payloads = json.loads((index_dir / "payloads.json").read_text(encoding="utf-8"))
    ids = json.loads((index_dir / "ids.json").read_text(encoding="utf-8"))
    repo = InMemoryVectorRepo()
    repo.ensure_collection(meta.get("collection") or index_dir.name, int(vectors.shape[1]))
    repo.upsert(ids, vectors, payloads)
    return repo, meta


def validate_index_meta(
    meta: dict,
    *,
    embedding_backend: str,
    embedding_model: str,
    vector_size: int | None = None,
    require_preprocess_version: str | None = PREPROCESS_VERSION,
) -> None:
    """Reject silent mismatch between index dump and runtime embedder."""
    backend = str(meta.get("embedding_backend") or "").lower()
    model = str(meta.get("embedding_model") or "")
    expected_backend = embedding_backend.lower().strip()
    if backend and backend != expected_backend:
        raise IndexCompatibilityError(
            f"Index backend={backend!r} does not match config backend={expected_backend!r}"
        )
    if model and model != embedding_model:
        raise IndexCompatibilityError(
            f"Index model={model!r} does not match config model={embedding_model!r}"
        )
    meta_dim = meta.get("vector_size")
    if vector_size is not None and meta_dim is not None and int(meta_dim) != int(vector_size):
        raise IndexCompatibilityError(
            f"Index vector_size={meta_dim} does not match embedder dim={vector_size}"
        )
    if require_preprocess_version is not None:
        version = index_preprocess_version(meta)
        if version and version != require_preprocess_version:
            raise IndexCompatibilityError(
                f"Index preprocess_version={version!r} does not match "
                f"runtime={require_preprocess_version!r}"
            )


def index_preprocess_version(meta: dict) -> str | None:
    preprocess = meta.get("preprocess") or {}
    if isinstance(preprocess, dict) and preprocess.get("version"):
        return str(preprocess["version"])
    raw = meta.get("preprocess_version")
    return str(raw) if raw else None


def find_latest_index(
    indexes_root: Path,
    *,
    embedding_backend: str | None = None,
    embedding_model: str | None = None,
    preprocess_version: str | None = None,
) -> Path | None:
    root = Path(indexes_root)
    candidates: list[Path] = []
    latest_meta = root / "latest_meta.json"
    if latest_meta.is_file():
        meta = json.loads(latest_meta.read_text(encoding="utf-8"))
        version = meta.get("index_version")
        if version and (root / version / "vectors.npy").is_file():
            candidates.append(root / version)
    candidates.extend(
        sorted(
            [p for p in root.iterdir() if p.is_dir() and (p / "vectors.npy").is_file()],
            reverse=True,
        )
    )
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        meta_path = path / "index_meta.json"
        if not meta_path.is_file():
            if embedding_backend is None:
                return path
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        got_preprocess = index_preprocess_version(meta)
        if preprocess_version and got_preprocess and got_preprocess != preprocess_version:
            continue
        if embedding_backend is not None:
            try:
                validate_index_meta(
                    meta,
                    embedding_backend=embedding_backend,
                    embedding_model=embedding_model or str(meta.get("embedding_model") or ""),
                    require_preprocess_version=None,
                )
            except IndexCompatibilityError:
                continue
        return path
    return None
