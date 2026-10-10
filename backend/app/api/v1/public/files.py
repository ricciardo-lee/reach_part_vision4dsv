from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response

from app.api.deps import get_current_app_user
from app.core.exceptions import NotFoundError
from app.models import AppUser
from app.utils.minio_client import LocalStorage, get_storage

router = APIRouter(prefix="/files", tags=["public-files"])


@router.get("/{object_key:path}")
async def get_file(object_key: str, _: AppUser = Depends(get_current_app_user)) -> Response:
    storage = get_storage()
    try:
        data = storage.get_bytes(object_key)
    except Exception as exc:  # noqa: BLE001
        raise NotFoundError("文件不存在") from exc

    media_type = "image/jpeg"
    if isinstance(storage, LocalStorage):
        meta = storage._path(object_key).with_suffix(Path(object_key).suffix + ".meta")
        if meta.exists():
            media_type = meta.read_text(encoding="utf-8").strip() or media_type
    return Response(content=data, media_type=media_type)
