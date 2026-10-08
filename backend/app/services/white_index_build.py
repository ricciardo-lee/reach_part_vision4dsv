"""Build a BiRefNet white-cutout index beside the full-frame gallery index."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.services.image_preprocessing import WHITE_PREPROCESS_VERSION

CHECKPOINT_DIRNAME = "_checkpoint"


def white_payload(payload: dict, *, index_version: str) -> dict:
    """Keep SKU, category, angle, and filename. Mark the new preprocess."""
    copied = dict(payload)
    copied["index_version"] = index_version
    copied["preprocess_version"] = WHITE_PREPROCESS_VERSION
    copied["embedding_backend"] = copied.get("embedding_backend") or "dinov2"
    return copied


def collect_white_rows(
    items: list[tuple[str, dict, object | None]],
    *,
    index_version: str,
) -> tuple[list[str], list[dict]]:
    """Drop rows whose cutout is missing. Those views stay out of the white index."""
    ids: list[str] = []
    payloads: list[dict] = []
    for source_id, payload, cutout in items:
        if cutout is None:
            continue
        ids.append(str(source_id))
        payloads.append(white_payload(payload, index_version=index_version))
    return ids, payloads


def white_index_meta(
    *,
    index_version: str,
    embedding_model: str,
    vector_size: int,
    source_index: str,
    image_count: int,
) -> dict:
    return {
        "index_version": index_version,
        "embedding_backend": "dinov2",
        "embedding_model": embedding_model,
        "vector_backend": "memory",
        "collection": f"parts_360_{index_version}",
        "vector_size": int(vector_size),
        "image_count": int(image_count),
        "preprocess": {"version": WHITE_PREPROCESS_VERSION, "target_size": 224},
        "preprocess_version": WHITE_PREPROCESS_VERSION,
        "source_index": source_index,
        "protocol_note": (
            "White tight-crop vectors use the same BiRefNet mask, bbox crop, "
            "and white letterbox as online query foregrounds."
        ),
    }


def checkpoint_dir(output_dir: Path) -> Path:
    return Path(output_dir) / CHECKPOINT_DIRNAME


def load_checkpoint(output_dir: Path) -> tuple[list[str], np.ndarray | None, list[dict], list[dict]]:
    folder = checkpoint_dir(output_dir)
    ids_path = folder / "ids.json"
    if not ids_path.is_file():
        return [], None, [], []
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    payloads = json.loads((folder / "payloads.json").read_text(encoding="utf-8"))
    failed_path = folder / "failed.json"
    failed = json.loads(failed_path.read_text(encoding="utf-8")) if failed_path.is_file() else []
    vectors_path = folder / "vectors.npy"
    vectors = np.load(vectors_path) if vectors_path.is_file() and ids else None
    return list(ids), vectors, list(payloads), list(failed)


def save_checkpoint(
    output_dir: Path,
    *,
    ids: list[str],
    vectors: np.ndarray | None,
    payloads: list[dict],
    failed: list[dict],
) -> None:
    folder = checkpoint_dir(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    (folder / "payloads.json").write_text(
        json.dumps(payloads, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "failed.json").write_text(json.dumps(failed, ensure_ascii=False), encoding="utf-8")
    if vectors is not None and len(ids):
        np.save(folder / "vectors.npy", vectors.astype(np.float32))


def write_white_index(
    output_dir: Path,
    *,
    ids: list[str],
    vectors: np.ndarray,
    payloads: list[dict],
    meta: dict,
) -> None:
    """Write the new dump only. Do not touch a sibling latest_meta.json."""
    if len(ids) != len(payloads) or vectors.shape[0] != len(ids):
        raise ValueError(
            f"White index size mismatch: ids={len(ids)} payloads={len(payloads)} vectors={vectors.shape[0]}"
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "vectors.npy", vectors.astype(np.float32))
    (output_dir / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
    (output_dir / "payloads.json").write_text(
        json.dumps(payloads, ensure_ascii=False), encoding="utf-8"
    )
    (output_dir / "index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def photo_candidates(photo_root: Path, payload: dict) -> list[Path]:
    """Paths to try. relative_path is Category/sku/file under the Photo360 root."""
    rel = str(payload.get("relative_path") or payload.get("filename") or "")
    if not rel:
        return []
    root = Path(photo_root)
    candidates = [root / rel, root / "Photo360" / rel]
    if root.is_dir():
        try:
            children = [child for child in root.iterdir() if child.is_dir() and child.name != "Photo360"]
        except OSError:
            children = []
        candidates.extend(child / rel for child in children)
    return candidates


def resolve_photo(
    photo_root: Path,
    payload: dict,
    extra_roots: list[Path] | None = None,
) -> Path | None:
    roots = [Path(photo_root), *(Path(item) for item in (extra_roots or []))]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for candidate in photo_candidates(root, payload):
            try:
                path = candidate.resolve()
            except OSError:
                continue
            if path in seen or not path.is_file() or not _inside(path, root):
                seen.add(path)
                continue
            return path
    return None


def locate_photo_root(photo_root: Path, payload: dict, meta: dict) -> tuple[Path, Path]:
    """Return the directory that actually contains this payload, and the file.

    Prefer the given root. If it has no file, use index_meta photo360_root.
    """
    meta_root = str(meta.get("photo360_root") or "").strip()
    extras = [Path(meta_root)] if meta_root else []
    found = resolve_photo(photo_root, payload, extra_roots=extras)
    if found is None:
        rel = payload.get("relative_path") or payload.get("filename")
        tried = [str(path) for path in photo_candidates(photo_root, payload)]
        if meta_root:
            tried.extend(str(path) for path in photo_candidates(Path(meta_root), payload))
        preview = "\n".join(f"  {item}" for item in tried[:8])
        raise FileNotFoundError(
            "找不到 360 原图，已停止，没有开始抠图。\n"
            f"relative_path={rel}\n"
            f"传入的 --photo-root={photo_root}\n"
            f"索引记录的 photo360_root={meta_root or '(无)'}\n"
            "这个目录下要能直接看到 Radiator 360s、Compressor 360 这类文件夹。\n"
            f"尝试过:\n{preview}"
        )
    if _inside(found, photo_root):
        return Path(photo_root).resolve(), found
    return Path(meta_root).resolve(), found
