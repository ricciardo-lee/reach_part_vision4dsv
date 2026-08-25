from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger("app.exceptions")


class AppError(Exception):
    def __init__(self, message: str, code: str = "app_error", status_code: int = 400, details: Any = None):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未授权", details: Any = None):
        super().__init__(message, code="unauthorized", status_code=401, details=details)


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权限", details: Any = None):
        super().__init__(message, code="forbidden", status_code=403, details=details)


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在", details: Any = None):
        super().__init__(message, code="not_found", status_code=404, details=details)


class RateLimitError(AppError):
    def __init__(self, message: str = "请求过于频繁，请稍后再试", details: Any = None):
        super().__init__(message, code="rate_limited", status_code=429, details=details)


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
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error | path=%s | error=%s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": "internal_error",
                "message": "服务内部错误",
                "details": str(exc) if settings.DEBUG else None,
            },
        )
