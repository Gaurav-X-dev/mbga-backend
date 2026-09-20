from pathlib import Path

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.main import app
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.schemas import (
    CurrentUserResponse,
    OTPRequestResponse,
    OTPVerifyResponse,
    TokenPair,
)

pytestmark = pytest.mark.unit


def account_fields(channel: LoginChannel, session_type: str = "access") -> dict:
    return {
        "user_id": "user-1",
        "login_channel": channel,
        "user_type": "ADMIN",
        "session_type": session_type,
        "account_status": "ACTIVE",
        "next_action": "OPEN_ADMIN_DASHBOARD",
    }


CHANNEL_CASES = [
    ("admin", LoginChannel.ADMIN, "/api/v1/admin/auth"),
    ("merchant", LoginChannel.MERCHANT, "/api/v1/merchant/auth"),
    ("customer", LoginChannel.CUSTOMER, "/api/v1/customer/auth"),
    ("customer-registration", LoginChannel.CUSTOMER, "/api/v1/customer/registration"),
    ("delivery", LoginChannel.DELIVERY, "/api/v1/delivery/auth"),
]


class ContractAuthService:
    def __init__(self) -> None:
        self.logout_all_user_id = None

    async def request_otp(self, payload, *, purpose=None, channel=None):
        assert channel in {case[1] for case in CHANNEL_CASES}
        assert purpose
        return OTPRequestResponse(request_id="request-id", expires_in=300, resend_after=30)

    async def resend_otp(self, payload, *, purpose, channel):
        assert payload.request_id == "request-id"
        assert purpose
        assert channel in {case[1] for case in CHANNEL_CASES}
        return OTPRequestResponse(request_id="request-id-2", expires_in=300, resend_after=30)

    async def verify_otp(self, payload, *, purpose, channel):
        assert payload.otp == "1234"
        assert purpose
        token_scope = "onboarding-access" if purpose == "CUSTOMER_REGISTRATION" else "access"
        return OTPVerifyResponse(
            token=TokenPair(access_token=token_scope, refresh_token="refresh-token", expires_in=900),
            **account_fields(channel),
        )

    async def refresh_token(self, payload, *, channel, session_types):
        assert payload.refresh_token == "refresh-token"
        return TokenPair(access_token="new-access-token", refresh_token="new-refresh-token", expires_in=900)

    async def logout(self, payload, *, channel):
        assert payload.refresh_token in {None, "refresh-token"}

    async def logout_all(self, access_token, *, channel, session_types):
        if not access_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTH_REQUIRED", "message": "Sign in to continue."})
        self.logout_all_user_id = "user-1"

    async def me(self, access_token, *, channel, session_types):
        if not access_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "AUTH_REQUIRED", "message": "Sign in to continue."})
        return CurrentUserResponse(
            display_name="Contract User",
            mobile_number="+919876543210",
            active_roles=[channel.value.lower()],
            effective_permissions=["dashboard.view"],
            status="ACTIVE",
            **account_fields(channel),
        )


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_authentication_service] = lambda: ContractAuthService()
    return TestClient(app)


@pytest.mark.parametrize(("name", "channel", "prefix"), CHANNEL_CASES)
def test_channel_auth_shared_contract(client: TestClient, name: str, channel: LoginChannel, prefix: str) -> None:
    request_response = client.post(
        f"{prefix}/otp/request",
        json={"mobile_number": "+919876543210", "device": {"device_type": "web", "device_id": "contract"}},
    )
    assert request_response.status_code == 202
    assert request_response.json()["request_id"] == "request-id"
    assert "1234" not in request_response.text

    resend_response = client.post(
        f"{prefix}/otp/resend",
        json={"request_id": "request-id", "device": {"device_type": "web", "device_id": "contract"}},
    )
    assert resend_response.status_code == 202
    assert resend_response.json()["request_id"] == "request-id-2"

    verify_response = client.post(
        f"{prefix}/otp/verify",
        json={"request_id": "request-id", "otp": "1234", "device": {"device_type": "web", "device_id": "contract"}},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["login_channel"] == channel.value

    refresh_response = client.post(f"{prefix}/token/refresh", json={"refresh_token": "refresh-token"})
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"] == "new-access-token"

    me_response = client.get(f"{prefix}/me", headers={"Authorization": "Bearer access-token"})
    assert me_response.status_code == 200
    assert me_response.json()["login_channel"] == channel.value

    logout_response = client.post(f"{prefix}/logout", json={"refresh_token": "refresh-token"})
    assert logout_response.status_code == 204

    logout_all_response = client.post(f"{prefix}/logout-all", headers={"Authorization": "Bearer access-token"}, json={})
    assert logout_all_response.status_code == 204


@pytest.mark.parametrize("otp", ["123", "12345", "12a4", 1234])
def test_all_channel_verify_routes_reject_non_four_digit_string_otp(client: TestClient, otp) -> None:
    for _, _, prefix in CHANNEL_CASES:
        response = client.post(f"{prefix}/otp/verify", json={"request_id": "request-id", "otp": otp})
        assert response.status_code == 422
        assert "detail" in response.json()


def test_openapi_route_reachability_and_uniqueness() -> None:
    openapi = app.openapi()
    seen: set[tuple[str, str]] = set()
    operation_ids: list[str] = []
    for path, methods in openapi["paths"].items():
        for method, operation in methods.items():
            if method.lower() not in {"get", "post", "patch", "delete", "put"}:
                continue
            key = (method.upper(), path)
            assert key not in seen
            seen.add(key)
            operation_ids.append(operation["operationId"])

    assert len(operation_ids) == len(set(operation_ids))
    assert ("POST", "/api/v1/admin/auth/otp/request") in seen
    assert ("POST", "/api/v1/customer/registration/otp/verify") in seen
    assert ("GET", "/api/v1/delivery/auth/me") in seen
    assert ("POST", "/api/v1/auth/otp/request") not in seen
    assert ("GET", "/api/v1/admin/login-channel") not in seen
    assert ("GET", "/api/v1/customer/login-channel") not in seen
    assert ("GET", "/api/v1/merchant/login-channel") not in seen
    assert ("GET", "/api/v1/delivery/login-channel") not in seen


def test_openapi_auth_contract_shapes() -> None:
    openapi = app.openapi()
    schemas = openapi["components"]["schemas"]
    otp_schema = schemas["OTPVerifyRequest"]
    assert otp_schema["properties"]["otp"]["type"] == "string"
    assert otp_schema["properties"]["otp"]["pattern"] == "^[0-9]{4}$"
    assert "otp" in otp_schema["required"]

    for prefix, schema_name in [
        ("/api/v1/admin/auth", "OTPVerifyRequest"),
        ("/api/v1/merchant/auth", "OTPVerifyRequest"),
        ("/api/v1/customer/auth", "OTPVerifyRequest"),
        ("/api/v1/customer/registration", "OTPVerifyRequest"),
        ("/api/v1/delivery/auth", "OTPVerifyRequest"),
    ]:
        verify_body = openapi["paths"][f"{prefix}/otp/verify"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert verify_body["$ref"].endswith(f"/{schema_name}")


def test_protected_admin_routes_declare_security_requirements() -> None:
    openapi = app.openapi()
    protected_prefixes = (
        "/api/v1/admin/dashboard",
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
        "/api/v1/admin/permissions",
        "/api/v1/admin/audit-logs",
    )
    for path, methods in openapi["paths"].items():
        if not path.startswith(protected_prefixes):
            continue
        for method, operation in methods.items():
            if method.lower() in {"get", "post", "patch", "delete", "put"}:
                assert operation.get("security"), f"{method.upper()} {path} is missing OpenAPI security"


def test_filtered_openapi_and_postman_artifacts_are_valid_json() -> None:
    docs = Path("docs")
    for name in ["admin", "merchant", "customer", "delivery"]:
        openapi_path = docs / f"openapi-{name}.json"
        postman_path = docs / f"MBGA_{name.title()}_API.postman_collection.json"
        assert openapi_path.exists()
        assert postman_path.exists()
        assert openapi_path.read_text(encoding="utf-8").startswith("{")
        assert postman_path.read_text(encoding="utf-8").startswith("{")


def test_removed_placeholder_routes_return_404(client: TestClient) -> None:
    for path in [
        "/api/v1/auth/otp/request",
        "/api/v1/auth/otp/verify",
        "/api/v1/auth/me",
        "/api/v1/admin/login-channel",
        "/api/v1/customer/login-channel",
        "/api/v1/merchant/login-channel",
        "/api/v1/delivery/login-channel",
    ]:
        assert client.get(path).status_code == 404


def test_channel_swagger_openapi_filters_are_reachable(client: TestClient) -> None:
    expected_prefixes = {
        "admin": "/api/v1/admin",
        "merchant": "/api/v1/merchant",
        "customer": "/api/v1/customer",
        "delivery": "/api/v1/delivery",
    }
    for channel, prefix in expected_prefixes.items():
        docs_response = client.get(f"/docs/{channel}")
        assert docs_response.status_code == 200
        openapi_response = client.get(f"/openapi/{channel}.json")
        assert openapi_response.status_code == 200
        paths = openapi_response.json()["paths"]
        assert paths
        assert all(path.startswith(prefix) or path == "/health" for path in paths)

    internal_response = client.get("/openapi/internal.json")
    assert internal_response.status_code == 200
    assert "/api/v1/admin/auth/otp/request" in internal_response.json()["paths"]


def _operation_items(schema: dict):
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method.lower() in {"get", "post", "patch", "delete", "put"}:
                yield path, method.upper(), operation


def test_each_channel_schema_has_unique_operations_and_one_primary_tag(client: TestClient) -> None:
    for channel in ["admin", "merchant", "customer", "delivery", "internal"]:
        schema = client.get(f"/openapi/{channel}.json").json()
        seen: set[tuple[str, str]] = set()
        operation_ids: list[str] = []
        for path, method, operation in _operation_items(schema):
            key = (method, path)
            assert key not in seen
            seen.add(key)
            operation_ids.append(operation["operationId"])
            assert len(operation.get("tags", [])) == 1, f"{method} {path} tags={operation.get('tags')}"
        assert len(operation_ids) == len(set(operation_ids))


def test_customer_schema_uses_exact_customer_tags_and_has_no_cross_channel_leakage(client: TestClient) -> None:
    schema = client.get("/openapi/customer.json").json()
    allowed_tags = {
        "Customer Authentication",
        "Customer Registration",
        "Customer Profile",
        "Customer Documents",
        "Customer Status",
        "Health",
    }
    for path, method, operation in _operation_items(schema):
        assert path.startswith("/api/v1/customer") or path == "/health"
        assert not path.startswith(("/api/v1/admin", "/api/v1/merchant", "/api/v1/delivery"))
        assert operation["tags"][0] in allowed_tags
        if path.startswith("/api/v1/customer/auth/"):
            assert operation["tags"] == ["Customer Authentication"]
        if path.startswith("/api/v1/customer/registration/documents"):
            assert operation["tags"] == ["Customer Documents"]
        elif path == "/api/v1/customer/registration/status":
            assert operation["tags"] == ["Customer Status"]
        elif path in {"/api/v1/customer/registration/profile", "/api/v1/customer/registration/fields", "/api/v1/customer/registration/submit"}:
            assert operation["tags"] == ["Customer Profile"]
        elif path.startswith("/api/v1/customer/registration/"):
            assert operation["tags"] == ["Customer Registration"]


def test_customer_onboarding_session_routes_are_documented_as_restricted(client: TestClient) -> None:
    schema = client.get("/openapi/customer.json").json()
    expected = {
        "/api/v1/customer/registration/token/refresh": "Refresh Onboarding Session",
        "/api/v1/customer/registration/logout": "End Onboarding Session",
        "/api/v1/customer/registration/logout-all": "End All Onboarding Sessions",
        "/api/v1/customer/registration/me": "Get Onboarding Registration Context",
    }
    for path, summary in expected.items():
        operation = next(iter(schema["paths"][path].values()))
        assert operation["summary"] == summary
        assert "does not grant full Customer App access" in operation["description"]
