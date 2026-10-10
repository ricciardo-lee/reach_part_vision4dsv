from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin import auth, manage
from app.api.v1.public import auth as public_auth
from app.api.v1.public import files, gallery, recognize, sessions
from app.api.deps import get_current_app_user
from app.schemas import APIResponse
from app.services.catalog import catalog_service, index_options
from fastapi import Depends
from app.models import AppUser

api_router = APIRouter(prefix="/api/v1")

public_router = APIRouter(prefix="/public")
public_router.include_router(public_auth.router)
public_router.include_router(sessions.router)
public_router.include_router(files.router)
public_router.include_router(gallery.router)
public_router.include_router(recognize.router)

vehicle_router = APIRouter(prefix="/vehicle", tags=["public-vehicle"])


@vehicle_router.get("/brands", response_model=APIResponse)
async def brands(_: AppUser = Depends(get_current_app_user)) -> APIResponse:
    return APIResponse(data=[item.model_dump() for item in await catalog_service.list_brands()])


@vehicle_router.get("/brands/indexed", response_model=APIResponse)
async def brands_indexed(_: AppUser = Depends(get_current_app_user)) -> APIResponse:
    options = await catalog_service.list_brands()
    return APIResponse(data=index_options(options))


@vehicle_router.get("/series", response_model=APIResponse)
async def series(brand: str, _: AppUser = Depends(get_current_app_user)) -> APIResponse:
    return APIResponse(data=[item.model_dump() for item in await catalog_service.list_series(brand)])


@vehicle_router.get("/series/indexed", response_model=APIResponse)
async def series_indexed(brand: str, _: AppUser = Depends(get_current_app_user)) -> APIResponse:
    options = await catalog_service.list_series(brand)
    return APIResponse(data=index_options(options))


@vehicle_router.get("/models", response_model=APIResponse)
async def models(brand: str, series: str, _: AppUser = Depends(get_current_app_user)) -> APIResponse:
    return APIResponse(data=[item.model_dump() for item in await catalog_service.list_models(brand, series)])


@vehicle_router.get("/models/indexed", response_model=APIResponse)
async def models_indexed(
    brand: str,
    series: str,
    _: AppUser = Depends(get_current_app_user),
) -> APIResponse:
    options = await catalog_service.list_models(brand, series)
    return APIResponse(data=index_options(options))


@vehicle_router.get("/years", response_model=APIResponse)
async def years(
    brand: str,
    series: str,
    model: str,
    _: AppUser = Depends(get_current_app_user),
) -> APIResponse:
    return APIResponse(data=[item.model_dump() for item in await catalog_service.list_years(brand, series, model)])


public_router.include_router(vehicle_router)

admin_router = APIRouter(prefix="/admin")
admin_router.include_router(auth.router)
admin_router.include_router(manage.router)

api_router.include_router(public_router)
api_router.include_router(admin_router)
