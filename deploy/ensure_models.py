"""Download query models into HF_HOME when the volume does not already have them."""

from __future__ import annotations

import os
import sys

from huggingface_hub import snapshot_download, try_to_load_from_cache


def _model_ids() -> list[str]:
    embedding = os.environ.get("EMBEDDING_MODEL_ID", "facebook/dinov2-base").strip()
    matting = os.environ.get("SEARCH_MATTING_MODEL_ID", "ZhengPeng7/BiRefNet").strip()
    ids: list[str] = []
    for model_id in (embedding, matting):
        if model_id and model_id not in ids:
            ids.append(model_id)
    return ids


def _cached(model_id: str) -> bool:
    if try_to_load_from_cache(model_id, "config.json") is None:
        return False
    for filename in ("model.safetensors", "pytorch_model.bin"):
        if try_to_load_from_cache(model_id, filename) is not None:
            return True
    return False


def main() -> int:
    os.environ.setdefault("HF_HOME", "/data/models")
    for model_id in _model_ids():
        if _cached(model_id):
            print(f"Model cache hit: {model_id}", flush=True)
            continue
        print(f"Downloading model: {model_id}", flush=True)
        snapshot_download(model_id)
        if not _cached(model_id):
            print(f"Model download finished but config.json is missing: {model_id}", file=sys.stderr)
            return 1
        print(f"Model ready: {model_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
