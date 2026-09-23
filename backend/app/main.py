from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse

from app.api import api_router
from app.config.app import get_settings
from app.shared.exceptions.handlers import register_exception_handlers
from app.shared.middleware.request_context import REQUEST_ID_HEADER, RequestContextMiddleware

CHANNEL_DOC_PREFIXES = {
    "admin": ["/api/v1/admin"],
    "merchant": ["/api/v1/merchant"],
    "customer": ["/api/v1/customer", "/health"],
    "delivery": ["/api/v1/delivery", "/health"],
}


def _primary_doc_tag(path: str, method: str) -> str:
    if path == "/health":
        return "Health"
    if path.startswith("/api/v1/customer/auth/"):
        return "Customer Authentication"
    if path.startswith(("/api/v1/customer/registration/documents", "/api/v1/customer/documents")):
        return "Customer Documents"
    # Public dropdown data for the registration form. Grouped under Registration rather than
    # given a tag of its own, because the customer channel's tag set is a contract the
    # OpenAPI matrix test asserts.
    if path == "/api/v1/customer/constants":
        return "Customer Registration"
    if path.startswith(("/api/v1/customer/customers", "/api/v1/customer/profile")):
        return "Customer Profile"
    if path == "/api/v1/customer/registration/status":
        return "Customer Status"
    if path in {"/api/v1/customer/registration/profile", "/api/v1/customer/registration/fields", "/api/v1/customer/registration/submit"}:
        return "Customer Profile"
    if path.startswith("/api/v1/customer/registration/"):
        return "Customer Registration"
    if path.startswith("/api/v1/admin/auth/"):
        return "Admin Authentication"
    if path.startswith("/api/v1/admin/dashboard"):
        return "Admin Dashboard"
    if path.startswith("/api/v1/admin/merchants"):
        return "Admin Merchants"
    if path.startswith("/api/v1/admin/users"):
        return "Admin Users"
    if path.startswith("/api/v1/admin/roles"):
        return "Admin Roles"
    if path.startswith("/api/v1/admin/permissions"):
        return "Admin Permissions"
    if path.startswith("/api/v1/admin/audit-logs"):
        return "Admin Audit Logs"
    if path.startswith("/api/v1/merchant/auth/"):
        return "Merchant Authentication"
    if path.startswith("/api/v1/merchant/delivery-users"):
        return "Merchant Delivery Users"
    if path == "/api/v1/merchant/constants":
        return "Merchant APIs"
    if path.startswith("/api/v1/merchant/kyc"):
        return "Merchant KYC Review"
    if path.startswith("/api/v1/merchant/documents"):
        return "Merchant Documents"
    if path.startswith("/api/v1/merchant/customers"):
        return "Merchant Customer Review"
    if path.startswith("/api/v1/merchant/"):
        return "Merchant APIs"
    if path.startswith("/api/v1/delivery/auth/"):
        return "Delivery Authentication"
    if path.startswith("/api/v1/delivery/"):
        return "Delivery APIs"
    return "Internal"


def _normalize_operation_docs(path: str, methods: dict) -> dict:
    normalized = {}
    onboarding_summaries = {
        "/api/v1/customer/registration/token/refresh": "Refresh Onboarding Session",
        "/api/v1/customer/registration/logout": "End Onboarding Session",
        "/api/v1/customer/registration/logout-all": "End All Onboarding Sessions",
        "/api/v1/customer/registration/me": "Get Onboarding Registration Context",
    }
    onboarding_description = (
        "Restricted onboarding-session operation for customer registration. "
        "This does not grant full Customer App access."
    )
    for method, operation in methods.items():
        if method.lower() not in {"get", "post", "patch", "delete", "put"}:
            normalized[method] = operation
            continue
        next_operation = dict(operation)
        next_operation["tags"] = [_primary_doc_tag(path, method)]
        if path in onboarding_summaries:
            next_operation["summary"] = onboarding_summaries[path]
            next_operation["description"] = onboarding_description
        normalized[method] = next_operation
    return normalized


def _filtered_openapi_schema(app: FastAPI, channel: str) -> dict:
    full_schema = app.openapi()
    prefixes = None if channel == "internal" else CHANNEL_DOC_PREFIXES[channel]
    paths = {
        path: _normalize_operation_docs(path, value)
        for path, value in full_schema["paths"].items()
        if prefixes is None or any(path.startswith(prefix) for prefix in prefixes)
    }
    return {
        **full_schema,
        "info": {**full_schema["info"], "title": f"{full_schema['info']['title']} - {channel.title()}"},
        "paths": paths,
    }


def _register_channel_docs(app: FastAPI) -> None:
    for channel in ["admin", "merchant", "customer", "delivery", "internal"]:
        openapi_url = f"/openapi/{channel}.json"
        docs_url = f"/docs/{channel}"

        async def openapi_endpoint(channel: str = channel) -> JSONResponse:
            return JSONResponse(_filtered_openapi_schema(app, channel))

        async def docs_endpoint(channel: str = channel, openapi_url: str = openapi_url):
            return get_swagger_ui_html(
                openapi_url=openapi_url,
                title=f"MBGA {channel.title()} API Docs",
            )

        app.add_api_route(openapi_url, openapi_endpoint, include_in_schema=False)
        app.add_api_route(docs_url, docs_endpoint, include_in_schema=False)


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.api_docs_enabled
    app = FastAPI(
        title=settings.app_name,
        # Starlette returns plain-text tracebacks when debug is on, bypassing the error handlers.
        debug=settings.debug and settings.is_local_environment,
        version=settings.app_version,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )
    # Outermost, so request IDs and security headers are also set on CORS and error responses.
    app.add_middleware(RequestContextMiddleware, hsts=not settings.is_local_environment)
    app.include_router(api_router, prefix=settings.api_prefix)
    if docs_enabled:
        _register_channel_docs(app)
    register_exception_handlers(app)

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
