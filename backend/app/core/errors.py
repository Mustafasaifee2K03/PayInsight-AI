"""Application error types and FastAPI exception handlers with a consistent error envelope.

Every error response has the shape::

    {"error": {"code": "...", "message": "...", "details": {...} | null}}
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("payinsight.errors")


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.headers = headers
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class AuthenticationError(AppError):
    status_code = 401
    code = "UNAUTHENTICATED"


class AuthorizationError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class SQLValidationError(AppError):
    status_code = 422
    code = "SQL_REJECTED"


class QueryTimeoutError(AppError):
    status_code = 408
    code = "QUERY_TIMEOUT"


class QueryResourceError(AppError):
    status_code = 422
    code = "QUERY_RESOURCE_LIMIT"


class QueryExecutionError(AppError):
    status_code = 500
    code = "QUERY_FAILED"


def _envelope(code: str, message: str, details: Any = None) -> dict:
    # request_id lets a user-reported error be matched to the server log line (hardening iteration 8)
    from .logging import request_id_var
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id_var.get()}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message, exc.details),
                            headers=exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=_envelope("HTTP_ERROR", str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=_envelope("VALIDATION_ERROR", "Request validation failed", details))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(status_code=500, content=_envelope("INTERNAL_ERROR", "An unexpected error occurred."))
