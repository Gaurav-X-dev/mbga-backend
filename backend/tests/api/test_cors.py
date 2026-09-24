import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.schemas import OTPRequestResponse

pytestmark = pytest.mark.unit


class FakeAuthenticationService:
    async def request_otp(self, payload, *, purpose=None, channel=None):
        assert channel == LoginChannel.ADMIN
        return OTPRequestResponse(request_id="request-1", expires_in=300, resend_after=30)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def _preflight(origin: str):
    client = TestClient(app)
    return client.options(
        "/api/v1/admin/auth/otp/request",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://localhost:5173"])
def test_cors_preflight_allows_local_frontend_origins(origin: str) -> None:
    response = _preflight(origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_cors_preflight_rejects_unknown_origin() -> None:
    response = _preflight("http://example.com")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_admin_otp_request_allows_configured_frontend_origin() -> None:
    clear_overrides()
    app.dependency_overrides[get_authentication_service] = lambda: FakeAuthenticationService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/admin/auth/otp/request",
        headers={"Origin": "http://127.0.0.1:5173"},
        json={
            "mobile_number": "+919000000001",
            "device": {
                "device_type": "web",
                "device_id": "web-panel",
            },
        },
    )

    assert response.status_code == 202
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.json()["request_id"] == "request-1"
    clear_overrides()
