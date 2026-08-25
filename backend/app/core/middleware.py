from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        client = request.client.host if request.client else "-"
        logger.info(
            "--> %s %s | client=%s | request_id=%s",
            request.method,
            request.url.path,
            client,
            request_id,
        )
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "<!! %s %s failed | %sms | request_id=%s",
                request.method,
                request.url.path,
                latency_ms,
                request_id,
            )
            raise

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "<-- %s %s | status=%s | %sms | request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            request_id,
        )
        response.headers["X-Request-ID"] = request_id
        return response


def register_request_logging(app: FastAPI) -> None:
    app.add_middleware(RequestLoggingMiddleware)
