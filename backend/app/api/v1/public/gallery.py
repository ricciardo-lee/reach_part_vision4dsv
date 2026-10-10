"""Serve 360 catalog photos for the mobile comparison view."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_current_app_user
from app.core.exceptions import NotFoundError
from app.models import AppUser
from app.schemas import APIResponse
from app.services.gallery import list_views, resolve_image

router = APIRouter(prefix="/gallery", tags=["public-gallery"])

_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.get("/{sku}/views", response_model=APIResponse)
async def gallery_views(sku: str, _: AppUser = Depends(get_current_app_user)) -> APIResponse:
    images = []
    for name in list_views(sku):
        images.append(
            {
                "name": name,
                "url": f"/api/v1/public/gallery/{quote(sku, safe='')}/files/{quote(name, safe='')}",
            }
        )
    return APIResponse(data=images)


@router.get("/{sku}/files/{name}")
async def gallery_file(sku: str, name: str, _: AppUser = Depends(get_current_app_user)) -> FileResponse:
    path = resolve_image(sku, name)
    if path is None:
        raise NotFoundError("360 图片不存在", message_key="gallery.not_found")
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lower(), "image/jpeg"))
