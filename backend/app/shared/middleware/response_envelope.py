"""
Response-envelope middleware.

Wraps every JSON response in the standard envelope the Delivery-App
frontend expects (API_REFERENCE §3):

    Success  →  { "success": true,  "data": <payload> }
    Error    →  { "success": false, "error": { "code": "…", "message": "…", "statusCode": N } }
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def install_envelope_handlers(app: FastAPI) -> None:
    """Register exception handlers that produce the standard error envelope for delivery channel."""

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if "/delivery" not in request.url.path:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        code, message = _extract_code_message(exc)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": code,
                    "message": message,
                    "statusCode": exc.status_code,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if "/delivery" not in request.url.path:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"detail": exc.errors()},
            )
        first_error = exc.errors()[0] if exc.errors() else {}
        field = " → ".join(str(loc) for loc in first_error.get("loc", []))
        message = f"{field}: {first_error.get('msg', 'Validation error')}" if field else "Validation error"
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": message,
                    "statusCode": 400,
                },
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        if "/delivery" not in request.url.path:
            raise exc
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                    "statusCode": 500,
                },
            },
        )


# ---------------------------------------------------------------------------
# Success-envelope helper – call from routers / services
# ---------------------------------------------------------------------------

def success_response(data: Any, status_code: int = 200) -> JSONResponse:
    """Return a JSONResponse with the standard success envelope."""
    return JSONResponse(status_code=status_code, content={"success": True, "data": data})


def paginated_response(
    items: list[dict],
    page: int,
    total_items: int,
    page_size: int,
    status_code: int = 200,
) -> JSONResponse:
    """Return a paginated success envelope."""
    total_pages = max(1, -(-total_items // page_size))  # ceil division
    return JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": {
                "items": items,
                "page": page,
                "totalPages": total_pages,
                "totalItems": total_items,
            },
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_code_message(exc: HTTPException) -> tuple[str, str]:
    """Pull code + message from HTTPException.detail (str or dict)."""
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", _status_to_code(exc.status_code))
        message = detail.get("message", code.replace("_", " ").title())
        return code, message
    if isinstance(detail, str):
        return _status_to_code(exc.status_code), detail
    return _status_to_code(exc.status_code), str(detail)


_STATUS_CODE_MAP: dict[int, str] = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


def _status_to_code(http_status: int) -> str:
    return _STATUS_CODE_MAP.get(http_status, "UNKNOWN_ERROR")
