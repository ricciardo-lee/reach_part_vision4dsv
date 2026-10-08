#!/usr/bin/env python3
"""Embed 360 photos with the same BiRefNet white crop the query uses.

Does not modify the source index or latest_meta.json. Views that fail matting
are omitted from the new index.

Example:
  cd backend && source .venv/bin/activate
  PYTHONPATH=. python ../scripts/build_birefnet_white_index.py \\
    --source-index-dir ../data/indexes/dinov2_20260923T055903Z \\
    --photo-root /path/to/Photo360 \\
    --output-dir ../data/indexes/dinov2_birefnet_white_v1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Set before NumPy/PyTorch load their thread pools.
_CPU = str(os.cpu_count() or 1)
os.environ.setdefault("OMP_NUM_THREADS", _CPU)
os.environ.setdefault("MKL_NUM_THREADS", _CPU)

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.ml.embedding import create_embedder  # noqa: E402
from app.services.image_preprocessing import build_white_foreground  # noqa: E402
from app.services.white_index_build import (  # noqa: E402
    load_checkpoint,
    locate_photo_root,
    resolve_photo,
    save_checkpoint,
    white_index_meta,
    white_payload,
    write_white_index,
)


def _load_source(index_dir: Path) -> tuple[list[str], list[dict], dict]:
    ids = json.loads((index_dir / "ids.json").read_text(encoding="utf-8"))
    payloads = json.loads((index_dir / "payloads.json").read_text(encoding="utf-8"))
    meta_path = index_dir / "index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if len(ids) != len(payloads):
        raise SystemExit(f"Source mismatch: ids={len(ids)} payloads={len(payloads)}")
    return [str(i) for i in ids], payloads, meta


def _load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def _load_batch(
    batch: list[tuple[str, dict]],
    photo_root: Path,
    workers: int,
) -> list[tuple[str, dict, Image.Image | None]]:
    paths = [resolve_photo(photo_root, payload) for _, payload in batch]

    def _open(path: Path | None) -> Image.Image | None:
        if path is None:
            return None
        return _load_rgb(path)

    if workers <= 1 or len(batch) <= 1:
        opened = [_open(path) for path in paths]
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(batch))) as pool:
            opened = list(pool.map(_open, paths))
    return [
        (source_id, payload, image)
        for (source_id, payload), image in zip(batch, opened, strict=True)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a BiRefNet white-cutout DINOv2 index")
    parser.add_argument("--source-index-dir", type=Path, required=True)
    parser.add_argument("--photo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--index-version", default="dinov2_birefnet_white_v1")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=8, help="Images per BiRefNet forward. Raise if RAM stays idle.")
    parser.add_argument("--workers", type=int, default=4, help="Threads that decode JPEGs ahead of inference")
    parser.add_argument("--limit", type=int, default=0, help="Process only the first N source rows")
    parser.add_argument("--checkpoint-every", type=int, default=200)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    source_dir = args.source_index_dir.resolve()
    photo_root = args.photo_root.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == source_dir:
        raise SystemExit("Refusing to write the white index over the source index")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_ids, source_payloads, source_meta = _load_source(source_dir)
    if args.limit > 0:
        source_ids = source_ids[: args.limit]
        source_payloads = source_payloads[: args.limit]
    if not source_payloads:
        raise SystemExit("Source index has no payloads")
    try:
        photo_root, sample = locate_photo_root(photo_root, source_payloads[0], source_meta)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Photo root: {photo_root}", flush=True)
    print(f"Sample file: {sample}", flush=True)

    done_ids, done_vectors, done_payloads, failed = load_checkpoint(output_dir)
    rows: list[np.ndarray] = []
    if done_vectors is not None and len(done_vectors) == len(done_ids):
        rows = [row for row in done_vectors]
        ids = list(done_ids)
        payloads = list(done_payloads)
    else:
        ids = []
        payloads = []
    done = set(ids)

    import torch

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS") or _CPU))
    print(
        f"Batch size {args.batch_size}, decode threads {args.workers}, "
        f"torch threads {torch.get_num_threads()}",
        flush=True,
    )

    from app.ml.birefnet_segmenter import BiRefNetSegmenter

    segmenter = BiRefNetSegmenter(
        model_id=settings.SEARCH_MATTING_MODEL_ID,
        device=args.device,
        input_size=settings.SEARCH_MATTING_INPUT_SIZE,
    )
    segmenter.load()
    embedder = create_embedder(
        settings.EMBEDDING_BACKEND,
        model_id=settings.EMBEDDING_MODEL_ID,
        device=args.device,
    )
    embedder.load()

    pending: list[tuple[str, dict]] = [
        (source_id, payload)
        for source_id, payload in zip(source_ids, source_payloads, strict=True)
        if source_id not in done
    ]
    print(f"Pending {len(pending)} images, already embedded {len(ids)}", flush=True)
    processed_since_save = 0
    started = time.perf_counter()
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start : start + args.batch_size]
        batch_started = time.perf_counter()
        print(
            f"batch {start // args.batch_size + 1} matting {len(batch)} images, "
            f"first={batch[0][0]}",
            flush=True,
        )
        loaded = _load_batch(batch, photo_root, args.workers)
        images = [item[2] for item in loaded if item[2] is not None]
        masks = segmenter.predict_masks(images) if images else []
        mask_iter = iter(masks)
        cutouts: list[Image.Image] = []
        cutout_rows: list[tuple[str, dict]] = []
        for source_id, payload, image in loaded:
            if image is None:
                failed.append(
                    {
                        "id": source_id,
                        "reason": "missing_file",
                        "relative_path": payload.get("relative_path"),
                    }
                )
                continue
            try:
                mask = next(mask_iter)
                cutout = (
                    build_white_foreground(
                        image,
                        mask,
                        target_size=settings.SEARCH_TARGET_SIZE,
                        margin_ratio=settings.SEARCH_SEGMENT_CROP_MARGIN,
                        min_area=settings.SEARCH_SEGMENT_MIN_AREA,
                        max_area=settings.SEARCH_SEGMENT_MAX_AREA,
                    )
                    if mask is not None
                    else None
                )
            except Exception as exc:  # noqa: BLE001
                cutout = None
                failed.append(
                    {
                        "id": source_id,
                        "reason": f"error:{exc}",
                        "relative_path": payload.get("relative_path"),
                    }
                )
                continue
            if cutout is None:
                failed.append(
                    {
                        "id": source_id,
                        "reason": "full_only",
                        "relative_path": payload.get("relative_path"),
                    }
                )
                continue
            cutouts.append(cutout)
            cutout_rows.append((source_id, payload))
        if cutouts:
            vectors = embedder.embed_images(cutouts)
            for vector, (source_id, payload) in zip(vectors, cutout_rows, strict=True):
                rows.append(np.asarray(vector, dtype=np.float32).reshape(-1))
                ids.append(source_id)
                payloads.append(white_payload(payload, index_version=args.index_version))
                done.add(source_id)
        elapsed = time.perf_counter() - batch_started
        done_n = start + len(batch)
        rate = done_n / max(time.perf_counter() - started, 1e-6)
        print(
            f"batch done in {elapsed:.1f}s, embedded {len(ids)}, skipped {len(failed)}, "
            f"{rate:.2f} images/s",
            flush=True,
        )
        processed_since_save += len(batch)
        if processed_since_save >= args.checkpoint_every:
            stacked = np.stack(rows).astype(np.float32) if rows else None
            save_checkpoint(output_dir, ids=ids, vectors=stacked, payloads=payloads, failed=failed)
            processed_since_save = 0
            print(f"checkpoint {len(ids)} embedded, {len(failed)} skipped", flush=True)

    vectors = np.stack(rows).astype(np.float32) if rows else None
    save_checkpoint(output_dir, ids=ids, vectors=vectors, payloads=payloads, failed=failed)
    if vectors is None or not len(ids):
        raise SystemExit("No white-cutout vectors were produced")

    meta = white_index_meta(
        index_version=args.index_version,
        embedding_model=getattr(embedder, "model_id", settings.EMBEDDING_MODEL_ID),
        vector_size=int(vectors.shape[1]),
        source_index=source_meta.get("index_version") or source_dir.name,
        image_count=len(ids),
    )
    write_white_index(output_dir, ids=ids, vectors=vectors, payloads=payloads, meta=meta)
    print(f"Wrote {len(ids)} vectors to {output_dir}", flush=True)
    print(f"Skipped {len(failed)} views", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
