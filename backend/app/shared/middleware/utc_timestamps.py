"""Make every JSON API timestamp unambiguous without changing response field names.

MySQL ``DATETIME`` values are UTC but have no timezone metadata.  Pydantic therefore used to
emit values such as ``2026-10-14T09:55:00``.  JavaScript treats that string as local time, so an
Indian client displayed it five hours and thirty minutes early.  This middleware adds the UTC
``Z`` marker to ISO datetime strings that do not already carry an offset.

It intentionally leaves date-only strings, values with ``Z``/an explicit offset, binary files,
HTML and PDFs untouched.  Keeping this at the API boundary also protects new endpoints whose
response schema accidentally uses a plain ``datetime`` in the future.
"""

import json
import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

_NAIVE_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$"
)


def normalize_utc_timestamps(value):
    """Recursively mark timezone-less ISO datetimes as UTC."""
    if isinstance(value, str):
        return f"{value}Z" if _NAIVE_ISO_DATETIME.fullmatch(value) else value
    if isinstance(value, list):
        return [normalize_utc_timestamps(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_utc_timestamps(item) for key, item in value.items()}
    return value


class UtcTimestampMiddleware(BaseHTTPMiddleware):
    """Apply the UTC timestamp contract to every JSON response from every channel."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = json.loads(body) if body else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        normalized = json.dumps(
            normalize_utc_timestamps(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        return Response(
            content=normalized,
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )
