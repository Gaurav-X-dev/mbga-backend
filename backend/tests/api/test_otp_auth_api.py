import pytest
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

ADMIN_FIELDS = {
    "user_id": "user-1",
    "login_channel": LoginChannel.ADMIN,
    "user_type": "ADMIN",
    "session_type": "access",
    "account_status": "ACTIVE",
    "role": "super_admin",
    "next_action": "OPEN_ADMIN_DASHBOARD",
}


class FakeAuthenticationService:
    async def request_otp(self, payload, *, purpose=None, channel=None):
        assert channel == LoginChannel.ADMIN
        return OTPRequestResponse(request_id="request-1", expires_in=300, resend_after=30)

    async def verify_otp(self, payload, *, purpose, channel):
        assert payload.otp == "1234"
        assert channel == LoginChannel.ADMIN
        assert purpose == "ADMIN_LOGIN"
        return OTPVerifyResponse(
            token=TokenPair(access_token="access-token", refresh_token="refresh-token", expires_in=900),
            **ADMIN_FIELDS,
        )

    async def me(self, access_token, *, channel, session_types):
        assert access_token == "access-token"
        assert channel == LoginChannel.ADMIN
        return CurrentUserResponse(
            display_name="Admin User",
            mobile_number="+919876543210",
            active_roles=["super_admin"],
            effective_permissions=["dashboard.view"],
            status="ACTIVE",
            **ADMIN_FIELDS,
        )


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_admin_otp_api_accepts_four_digit_string_flow() -> None:
    clear_overrides()
    app.dependency_overrides[get_authentication_service] = lambda: FakeAuthenticationService()
    client = TestClient(app)

    request_response = client.post(
        "/api/v1/admin/auth/otp/request",
        json={"mobile_number": "+919876543210", "device": {"device_type": "web"}},
    )
    assert request_response.status_code == 202
    assert "1234" not in request_response.text
    assert request_response.json()["request_id"] == "request-1"

    verify_response = client.post(
        "/api/v1/admin/auth/otp/verify",
        json={"request_id": "request-1", "otp": "1234"},
    )
    assert verify_response.status_code == 200
    assert verify_response.json()["token"]["access_token"] == "access-token"

    me_response = client.get("/api/v1/admin/auth/me", headers={"Authorization": "Bearer access-token"})
    assert me_response.status_code == 200
    assert me_response.json()["effective_permissions"] == ["dashboard.view"]
    clear_overrides()


@pytest.mark.parametrize("otp", ["123", "12345", "12a4", 1234])
def test_admin_otp_api_rejects_non_four_digit_string_values(otp) -> None:
    clear_overrides()
    app.dependency_overrides[get_authentication_service] = lambda: FakeAuthenticationService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/auth/otp/verify",
        json={"request_id": "request-1", "otp": otp},
    )

    assert response.status_code == 422
    clear_overrides()
