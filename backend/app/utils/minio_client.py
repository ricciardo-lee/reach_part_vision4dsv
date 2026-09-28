from __future__ import annotations

import logging
import mimetypes
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.core.config import settings

logger = logging.getLogger(__name__)


class LocalStorage:
    """Dev-friendly local disk storage used when MinIO is unavailable."""

    def __init__(self) -> None:
        self.root = Path(settings.LOCAL_STORAGE_DIR)
        if not self.root.is_absolute():
            self.root = Path(__file__).resolve().parents[2] / self.root
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket = "local"

    def ensure_bucket(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        path = (self.root / object_key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError("invalid object key")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        path = self._path(object_key)
        path.write_bytes(data)
        meta = path.with_suffix(path.suffix + ".meta")
        meta.write_text(content_type or "application/octet-stream", encoding="utf-8")

    def get_bytes(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()

    def delete_object(self, object_key: str) -> None:
        path = self._path(object_key)
        meta = path.with_suffix(path.suffix + ".meta")
        if path.exists():
            path.unlink()
        if meta.exists():
            meta.unlink()

    def presigned_get_url(self, object_key: str, expires_hours: int = 2) -> str:
        # Served by FastAPI static-like endpoint
        return f"/api/v1/public/files/{quote(object_key, safe='/')}"


class MinioStorage:
    def __init__(self) -> None:
        from minio import Minio

        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info("Created MinIO bucket %s", self.bucket)

    def put_bytes(self, object_key: str, data: bytes, content_type: str) -> None:
        import io

        self.client.put_object(
            self.bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def delete_object(self, object_key: str) -> None:
        try:
            self.client.remove_object(self.bucket, object_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to delete object %s: %s", object_key, exc)

    def presigned_get_url(self, object_key: str, expires_hours: int = 2) -> str:
        from urllib.parse import urljoin

        if settings.MINIO_PUBLIC_BASE_URL:
            return urljoin(settings.MINIO_PUBLIC_BASE_URL.rstrip("/") + "/", object_key)
        return self.client.presigned_get_object(
            self.bucket,
            object_key,
            expires=timedelta(hours=expires_hours),
        )


_storage = None


def get_storage():
    global _storage
    if _storage is not None:
        return _storage

    backend = settings.resolved_storage_backend
    if backend == "local":
        _storage = LocalStorage()
        logger.info("Using local disk storage at %s", _storage.root)
        return _storage

    _storage = MinioStorage()
    logger.info("Using MinIO storage at %s", settings.MINIO_ENDPOINT)
    return _storage
