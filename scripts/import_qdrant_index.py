#!/usr/bin/env python3
"""Import a memory index dump (vectors.npy) into Qdrant and set parts_360_current alias.

Example:
  cd backend && source .venv/bin/activate
  PYTHONPATH=. python ../scripts/import_qdrant_index.py \\
    --index-dir ../data/indexes/dinov2_20260923T055903Z \\
    --qdrant-url http://127.0.0.1:6333
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.repositories.vector_repo import QdrantVectorRepo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Import DINOv2 index dump into Qdrant")
    parser.add_argument(
        "--index-dir",
        type=Path,
        required=True,
        help="Directory containing vectors.npy / payloads.json / ids.json / index_meta.json",
    )
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--alias", default="parts_360_current")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument(
        "--collection",
        default=None,
        help="Override collection name (default: from index_meta.collection)",
    )
    args = parser.parse_args()

    index_dir = args.index_dir.resolve()
    meta_path = index_dir / "index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    vectors = np.load(index_dir / "vectors.npy")
    payloads = json.loads((index_dir / "payloads.json").read_text(encoding="utf-8"))
    ids = json.loads((index_dir / "ids.json").read_text(encoding="utf-8"))
    if not (len(ids) == len(payloads) == vectors.shape[0]):
        raise SystemExit(
            f"Mismatch: ids={len(ids)} payloads={len(payloads)} vectors={vectors.shape[0]}"
        )

    collection = args.collection or meta.get("collection") or f"parts_360_{index_dir.name}"
    dim = int(vectors.shape[1])
    print(f"Importing {vectors.shape[0]} vectors dim={dim} -> {collection}")

    repo = QdrantVectorRepo(url=args.qdrant_url, api_key=args.api_key)
    repo.ensure_collection(collection, dim)

    batch = args.batch_size
    for start in range(0, len(ids), batch):
        end = min(start + batch, len(ids))
        repo.upsert(ids[start:end], vectors[start:end], payloads[start:end])
        print(f"  upserted {end}/{len(ids)}")

    repo.set_alias(collection, alias=args.alias)
    print(f"Alias {args.alias} -> {collection}")
    print(f"Count={repo.count()}")

    # Write latest_meta next to index for runtime discovery
    latest = index_dir.parent / "latest_meta.json"
    latest.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
