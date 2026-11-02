"""Admin catalog Excel maintenance for vision_* OE / vehicle / radiator-spec tables."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import require_permission
from app.core.constants import SUPPORTED_CATEGORY_IDS
from app.core.exceptions import AppError
from app.models import (
    AdminUser,
    CatalogImportLog,
    VisionPartOe,
    VisionPartVehicle,
    VisionRadiatorSpec,
)
from app.schemas import APIResponse
from app.services import catalog_admin

router = APIRouter(prefix="/catalog", tags=["admin-catalog"])


class OePatch(BaseModel):
    category: Optional[str] = None
    oe: Optional[str] = None
    is_active: Optional[bool] = None


class VehiclePatch(BaseModel):
    make_name: Optional[str] = None
    model_name: Optional[str] = None
    year: Optional[str] = None
    is_active: Optional[bool] = None


def _xlsx_response(content: bytes, filename: str) -> StreamingResponse:
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/oe", response_model=APIResponse)
async def list_oe(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    _: AdminUser = Depends(require_permission("catalog:read")),
) -> APIResponse:
    qs = VisionPartOe.all()
    if keyword.strip():
        qs = qs.filter(oe__icontains=keyword.strip())
    total = await qs.count()
    items = await qs.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return APIResponse(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": x.id,
                    "category": x.category,
                    "material_code": x.material_code,
                    "oe": x.oe,
                    "is_active": x.is_active,
                }
                for x in items
            ],
        }
    )


@router.get("/vehicles", response_model=APIResponse)
async def list_vehicles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    _: AdminUser = Depends(require_permission("catalog:read")),
) -> APIResponse:
    qs = VisionPartVehicle.all()
    if keyword.strip():
        qs = qs.filter(make_name__icontains=keyword.strip())
    total = await qs.count()
    items = await qs.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return APIResponse(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": x.id,
                    "material_code": x.material_code,
                    "make_name": x.make_name,
                    "model_name": x.model_name,
                    "year": x.year,
                    "is_active": x.is_active,
                }
                for x in items
            ],
        }
    )


@router.get("/import-logs", response_model=APIResponse)
async def import_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: AdminUser = Depends(require_permission("catalog:read")),
) -> APIResponse:
    qs = CatalogImportLog.all()
    total = await qs.count()
    items = await qs.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return APIResponse(
        data={
            "total": total,
            "items": [
                {
                    "id": x.id,
                    "kind": x.kind,
                    "filename": x.filename,
                    "total_rows": x.total_rows,
                    "success_count": x.success_count,
                    "failure_count": x.failure_count,
                    "errors": x.errors,
                    "operator": x.operator,
                    "created_at": x.created_at.isoformat() if x.created_at else None,
                }
                for x in items
            ],
        }
    )


@router.get("/specs/radiator", response_model=APIResponse)
async def list_radiator_specs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    _: AdminUser = Depends(require_permission("catalog:read")),
) -> APIResponse:
    qs = VisionRadiatorSpec.all()
    if keyword.strip():
        qs = qs.filter(material_code__icontains=keyword.strip())
    total = await qs.count()
    items = await qs.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    preview_fields = (
        "core_material",
        "tank_material",
        "inlet_location",
        "outlet_location",
        "core_row_quantity",
    )
    return APIResponse(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "schema_pending": False,
            "items": [
                {
                    "id": x.id,
                    "material_code": x.material_code,
                    "is_active": x.is_active,
                    **{f: getattr(x, f, None) for f in preview_fields},
                }
                for x in items
            ],
        }
    )


@router.get("/specs/{category}", response_model=APIResponse)
async def list_specs(
    category: str,
    _: AdminUser = Depends(require_permission("catalog:read")),
) -> APIResponse:
    if category == "radiator":
        raise AppError("Use /catalog/specs/radiator", code="use_radiator_route", status_code=400)
    if category not in SUPPORTED_CATEGORY_IDS:
        raise AppError("Unsupported category", code="unsupported_category", status_code=400)
    return APIResponse(
        data={
            "category": category,
            "schema_pending": True,
            "items": [],
            "message": "Technical-spec headers are pending confirmation",
        }
    )


@router.get("/{kind}/template")
async def download_template(
    kind: str,
    _: AdminUser = Depends(require_permission("catalog:read")),
):
    if kind.startswith("spec-"):
        kind = "spec_" + kind.split("-", 1)[1]
    content = catalog_admin.export_template(kind)
    return _xlsx_response(content, f"{kind}_template.xlsx")


@router.get("/{kind}/export")
async def export_kind(
    kind: str,
    keyword: str = "",
    _: AdminUser = Depends(require_permission("catalog:read")),
):
    content = await catalog_admin.export_data(kind, keyword=keyword)
    return _xlsx_response(content, f"{kind}_export.xlsx")


@router.post("/{kind}/import", response_model=APIResponse)
async def import_kind(
    kind: str,
    file: UploadFile = File(...),
    admin: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    raw = await file.read()
    if not raw:
        raise AppError("Empty file", code="empty_file", status_code=400)
    log = await catalog_admin.import_excel(
        kind=kind,
        file_bytes=raw,
        filename=file.filename or "upload.xlsx",
        operator=admin.username,
    )
    return APIResponse(
        data={
            "id": log.id,
            "success_count": log.success_count,
            "failure_count": log.failure_count,
            "errors": log.errors,
        },
        message="imported",
    )


@router.get("/specs/{category}/template")
async def specs_template(
    category: str,
    _: AdminUser = Depends(require_permission("catalog:read")),
):
    if category not in SUPPORTED_CATEGORY_IDS:
        raise AppError("Unsupported category", code="unsupported_category", status_code=400)
    content = catalog_admin.export_template(f"spec_{category}")
    return _xlsx_response(content, f"spec_{category}_template.xlsx")


@router.get("/specs/{category}/export")
async def specs_export(
    category: str,
    keyword: str = "",
    _: AdminUser = Depends(require_permission("catalog:read")),
):
    if category != "radiator":
        raise AppError("Export only available for radiator specs", code="bad_kind", status_code=400)
    content = await catalog_admin.export_data("spec_radiator", keyword=keyword)
    return _xlsx_response(content, "spec_radiator_export.xlsx")


@router.post("/specs/{category}/import", response_model=APIResponse)
async def specs_import(
    category: str,
    file: UploadFile = File(...),
    admin: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    if category not in SUPPORTED_CATEGORY_IDS:
        raise AppError("Unsupported category", code="unsupported_category", status_code=400)
    raw = await file.read()
    log = await catalog_admin.import_excel(
        kind=f"spec_{category}",
        file_bytes=raw,
        filename=file.filename or "upload.xlsx",
        operator=admin.username,
    )
    return APIResponse(
        data={
            "id": log.id,
            "success_count": log.success_count,
            "failure_count": log.failure_count,
            "errors": log.errors,
        },
        message="imported",
    )


@router.patch("/oe/{item_id}", response_model=APIResponse)
async def patch_oe(
    item_id: int,
    payload: OePatch,
    _: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    item = await VisionPartOe.get_or_none(id=item_id)
    if not item:
        raise AppError("Not found", code="not_found", status_code=404)
    data = payload.model_dump(exclude_unset=True)
    if "oe" in data and data["oe"]:
        from app.services.catalog import normalize_oe

        data["oe_normalized"] = normalize_oe(data["oe"])
    await item.update_from_dict(data).save()
    return APIResponse(data={"id": item.id})


@router.delete("/oe/{item_id}", response_model=APIResponse)
async def delete_oe(
    item_id: int,
    _: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    item = await VisionPartOe.get_or_none(id=item_id)
    if not item:
        raise AppError("Not found", code="not_found", status_code=404)
    item.is_active = False
    await item.save()
    return APIResponse(message="deleted")


@router.patch("/vehicles/{item_id}", response_model=APIResponse)
async def patch_vehicle(
    item_id: int,
    payload: VehiclePatch,
    _: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    item = await VisionPartVehicle.get_or_none(id=item_id)
    if not item:
        raise AppError("Not found", code="not_found", status_code=404)
    await item.update_from_dict(payload.model_dump(exclude_unset=True)).save()
    return APIResponse(data={"id": item.id})


@router.delete("/vehicles/{item_id}", response_model=APIResponse)
async def delete_vehicle(
    item_id: int,
    _: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    item = await VisionPartVehicle.get_or_none(id=item_id)
    if not item:
        raise AppError("Not found", code="not_found", status_code=404)
    item.is_active = False
    await item.save()
    return APIResponse(message="deleted")


@router.delete("/specs/radiator/{item_id}", response_model=APIResponse)
async def delete_radiator_spec(
    item_id: int,
    _: AdminUser = Depends(require_permission("catalog:write")),
) -> APIResponse:
    item = await VisionRadiatorSpec.get_or_none(id=item_id)
    if not item:
        raise AppError("Not found", code="not_found", status_code=404)
    item.is_active = False
    await item.save()
    return APIResponse(message="deleted")
