"""The delivery app's response envelope, applied to the delivery channel only.

The delivery app's HTTP client unwraps every response itself (API_REFERENCE §3):

    success  ->  {"success": true,  "data": <payload>}
    error    ->  {"success": false, "error": {"code", "message", "statusCode"}}

The platform's own envelope is `{"detail": {code, message, fields, request_id}}`, which every
other channel and both other apps are built against. Rather than change one of them, this
middleware re-shapes responses on the way out for `/api/v1/delivery/*` alone.

**It ships switched off.** `DELIVERY_RESPONSE_ENVELOPE=true` turns it on. The delivery app is
already signed in against the platform's raw shapes on the auth and notification routes, so
turning this on without the app developer expecting it would break an integration that works
today. The switch exists so that flip is a one-line deployment change made deliberately, and
reversible in the same breath.

`request_id` is not dropped when the envelope is on - it stays on the `X-Request-Id` response
header, which is where a support conversation should be reading it from anyway.
"""

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

#: Only this channel. Matching on the path prefix rather than on the resolved session keeps the
#: rule readable and applies it to 401s, which have no session at all.
DELIVERY_PREFIX = "/api/v1/delivery"

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


#: Where the switch lives. Read off `app.state` per request rather than captured at start-up, so
#: the middleware can stay installed and a deployment (or a test) flips one boolean.
STATE_FLAG = "delivery_response_envelope"


class DeliveryEnvelopeMiddleware(BaseHTTPMiddleware):
    """Re-wraps delivery-channel JSON responses into the app's envelope."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if not getattr(request.app.state, STATE_FLAG, False):
            return response
        if not request.url.path.startswith(DELIVERY_PREFIX):
            return response
        if response.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            # Not ours to reshape. Hand it back exactly as it was rather than turning an odd
            # response into a confident-looking envelope.
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        wrapped = (
            {"success": True, "data": payload}
            if response.status_code < 400
            else {"success": False, "error": _error(payload, response.status_code)}
        )
        headers = {
            key: value
            for key, value in response.headers.items()
            # Recomputed by the new response; a stale length truncates the body.
            if key.lower() not in {"content-length", "content-type"}
        }
        return JSONResponse(content=wrapped, status_code=response.status_code, headers=headers)


def _error(payload: object, status_code: int) -> dict[str, object]:
    """Pull a code and a message out of whatever shape the error arrived in.

    The platform's own envelope is the common case. A plain string, a bare list from a
    validation error, and an unrecognised shape all still have to produce something the app can
    render, because the alternative is a driver staring at "UNKNOWN_ERROR".
    """
    fallback = _STATUS_CODES.get(status_code, "ERROR")
    detail: object = payload
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]

    if isinstance(detail, dict):
        return {
            "code": detail.get("code") or fallback,
            "message": detail.get("message") or "Something went wrong. Please try again.",
            "statusCode": status_code,
        }
    if isinstance(detail, str) and detail:
        return {"code": fallback, "message": detail, "statusCode": status_code}
    if isinstance(detail, list) and detail:
        first = detail[0]
        message = first.get("msg") if isinstance(first, dict) else None
        return {
            "code": "VALIDATION_ERROR",
            "message": message or "Please check the details and try again.",
            "statusCode": status_code,
        }
    return {
        "code": fallback,
        "message": "Something went wrong. Please try again.",
        "statusCode": status_code,
    }
