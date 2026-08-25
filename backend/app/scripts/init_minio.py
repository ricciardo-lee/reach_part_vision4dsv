#!/usr/bin/env python3
"""Ensure MinIO bucket exists."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.utils.minio_client import get_storage  # noqa: E402


def main() -> None:
    storage = get_storage()
    storage.ensure_bucket()
    print(f"MinIO bucket ready: {storage.bucket}")


if __name__ == "__main__":
    main()
