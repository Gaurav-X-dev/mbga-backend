"""Exception handlers producing the project error envelope.

Envelope: ``{"detail": {"code", "message", "fields", "request_id"}}``.

Coded errors (``detail`` is a dict with ``code``) get this envelope on every route. Plain-text and
list-style errors are converted on authentication and registration routes only, so existing web-panel
screens that still read plain-text admin errors keep working.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.modules.authentication.mobile_number import (
    INVALID_MOBILE_MESSAGE,
    InvalidMobileNumberError,
)
from app.shared.exceptions.api_error import error_detail
from app.shared.middleware.request_context import current_request_id

logger = logging.getLogger(__name__)

AUTH_PATH_MARKERS = ("/auth/", "/customer/registration")
_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def is_auth_path(path: str) -> bool:
    return path.startswith("/api/") and any(marker in path for marker in AUTH_PATH_MARKERS)


def _envelope(detail: dict[str, Any]) -> dict[str, Any]:
    return {"detail": {**detail, "fields": detail.get("fields") or [], "request_id": current_request_id()}}


def _validation_fields(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = []
    for error in errors:
        loc = [str(part) for part in error.get("loc", ()) if part not in ("body", "query", "path", "header")]
        fields.append({"field": ".".join(loc) or None, "code": error.get("type", "invalid"), "message": error.get("msg", "Invalid value")})
    return fields


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidMobileNumberError)
    async def invalid_mobile_number_handler(_: Request, exc: InvalidMobileNumberError) -> JSONResponse:
        detail = error_detail("INVALID_MOBILE_NUMBER", INVALID_MOBILE_MESSAGE, [{"field": "mobile_number", "code": "invalid_mobile_number", "message": INVALID_MOBILE_MESSAGE}])
        return JSONResponse(status_code=422, content=_envelope(detail))

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content=_envelope(detail), headers=headers)
        if is_auth_path(request.url.path):
            code = _STATUS_CODES.get(exc.status_code, "ERROR")
            message = detail if isinstance(detail, str) and exc.status_code < 500 else None
            return JSONResponse(status_code=exc.status_code, content=_envelope(error_detail(code, message)), headers=headers)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = list(exc.errors())
        if is_auth_path(request.url.path):
            detail = error_detail("VALIDATION_ERROR", fields=_validation_fields(errors))
            return JSONResponse(status_code=422, content=_envelope(detail))
        # Admin/merchant web-panel routes keep FastAPI's list format, which the panel maps to form fields.
        safe = [{key: value for key, value in error.items() if key in {"type", "loc", "msg", "ctx"}} for error in errors]
        for item in safe:
            if "ctx" in item:
                item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        return JSONResponse(status_code=422, content={"detail": safe})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error (request_id=%s, path=%s)", current_request_id(), request.url.path)
        return JSONResponse(status_code=500, content=_envelope(error_detail("INTERNAL_ERROR")))
