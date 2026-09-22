"""OpenAPI documentation for the project error envelope."""

from typing import Any

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str | None = Field(description="Dotted field path, e.g. `device.device_id`.")
    code: str
    message: str


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Safe, user-facing message.")
    fields: list[FieldError] = Field(default_factory=list)
    request_id: str | None = Field(default=None, description="Also returned in the X-Request-ID header.")


class ErrorResponse(BaseModel):
    detail: ErrorDetail


_DESCRIPTIONS = {
    400: "Invalid request state (for example an incorrect or used code).",
    401: "Missing, invalid, expired or revoked session.",
    403: "The account may not perform this action or use this app.",
    404: "Not found.",
    409: "Conflicts with existing data.",
    410: "The link has expired.",
    413: "The uploaded file is larger than the allowed size.",
    415: "Unsupported file type.",
    422: "Validation error. `detail.fields` lists the invalid fields.",
    429: "Too many requests. See the Retry-After header.",
    503: "A dependent service (for example SMS delivery) is unavailable.",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse, "description": _DESCRIPTIONS[code]} for code in status_codes}
