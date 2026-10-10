from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.i18n import locale_from_request, t, translate_message

logger = logging.getLogger("app.exceptions")


class AppError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "app_error",
        status_code: int = 400,
        details: Any = None,
        *,
        message_key: str | None = None,
        message_params: dict | None = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        self.message_key = message_key
        self.message_params = message_params or {}
        super().__init__(message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未授权", details: Any = None, *, message_key: str | None = None):
        super().__init__(
            message,
            code="unauthorized",
            status_code=401,
            details=details,
            message_key=message_key or "errors.unauthorized",
        )


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权限", details: Any = None, *, message_key: str | None = None):
        super().__init__(
            message,
            code="forbidden",
            status_code=403,
            details=details,
            message_key=message_key or "errors.forbidden",
        )


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在", details: Any = None, *, message_key: str | None = None):
        super().__init__(
            message,
            code="not_found",
            status_code=404,
            details=details,
            message_key=message_key or "errors.not_found",
        )


class RateLimitError(AppError):
    def __init__(
        self,
        message: str = "请求过于频繁，请稍后再试",
        details: Any = None,
        *,
        message_key: str | None = None,
    ):
        super().__init__(
            message,
            code="rate_limited",
            status_code=429,
            details=details,
            message_key=message_key or "errors.rate_limited",
        )


def _localize_app_error(request: Request, exc: AppError) -> str:
    locale = locale_from_request(request)
    # Admin API keeps Chinese defaults.
    if "/admin/" in request.url.path:
        return exc.message
    if exc.message_key:
        return t(exc.message_key, locale, **exc.message_params)
    return translate_message(exc.message, locale)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "AppError | path=%s | code=%s | status=%s | message=%s",
            request.url.path,
            exc.code,
            exc.status_code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "code": exc.code,
                "message": _localize_app_error(request, exc),
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error | path=%s | error=%s", request.url.path, exc)
        locale = locale_from_request(request)
        message = (
            "服务内部错误"
            if "/admin/" in request.url.path
            else t("errors.internal", locale)
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": "internal_error",
                "message": message,
                "details": str(exc) if settings.DEBUG else None,
            },
        )
