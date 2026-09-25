"""Request correlation ID and response security headers.

Implemented as pure ASGI middleware so it also covers error responses and does not buffer bodies.
"""

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.notifications.autodispatch import schedule_dispatch, take_queued

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Authentication and onboarding responses carry tokens or account state and must never be cached.
NO_STORE_PATH_MARKERS = ("/auth/", "/customer/registration")


def current_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _SAFE_REQUEST_ID.match(incoming) else str(uuid4())
        token = _request_id.set(request_id)
        path: str = scope.get("path", "")
        is_api = path.startswith("/api/")
        no_store = is_api and any(marker in path for marker in NO_STORE_PATH_MARKERS)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
                if is_api:
                    headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                if no_store:
                    headers["Cache-Control"] = "no-store"
                    headers["Pragma"] = "no-cache"
                if self.hsts:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _request_id.reset(token)
            # After the response, never during it: a queued notification is delivered now
            # rather than on the worker's next sweep, and Firebase being slow can never
            # make this request slow.
            if take_queued():
                schedule_dispatch()
