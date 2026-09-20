"""Regression: invalid mobile numbers must return a controlled 422, never a 500 traceback."""

import pytest
from fastapi.testclient import TestClient

from app.config.app import get_settings
from app.main import app
from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.schemas import OTPRequestResponse
from app.modules.authentication.service import AuthenticationService

pytestmark = pytest.mark.unit


class _NoUserSession:
    async def scalar(self, *_args, **_kwargs):
        return None


class _Repository:
    session = _NoUserSession()


def _service() -> AuthenticationService:
    # Only the repository is reached for valid numbers; OTP storage and delivery are never used.
    return AuthenticationService(_Repository(), otp_service=None, otp_provider=None, settings=get_settings())


@pytest.fixture
def client():
    app.dependency_overrides[get_authentication_service] = _service
    # raise_server_exceptions=False: an unhandled error must show up as a 500 response, not pass silently.
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


INVALID_CASES = [
    ({"mobile_number": "+449876543210"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "9876543210", "country_code": "+44"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "98765432"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "98765432101"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "0000000001"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "+910000000001"}, "INVALID_MOBILE_NUMBER"),
    ({"mobile_number": "98765abc10"}, "INVALID_MOBILE_NUMBER"),
]


@pytest.mark.parametrize("channel", ["admin", "merchant", "delivery", "customer"])
@pytest.mark.parametrize(("body", "code"), INVALID_CASES)
def test_invalid_mobile_returns_controlled_422(client: TestClient, channel: str, body: dict, code: str) -> None:
    response = client.post(
        f"/api/v1/{channel}/auth/otp/request",
        json=body,
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["message"] == "Enter a valid 10-digit Indian mobile number."
    assert detail["fields"][0]["field"] == "mobile_number"
    assert detail["request_id"] == response.headers["x-request-id"]
    assert "Traceback" not in response.text
    # The error is returned inside the CORS middleware, so the browser can read it.
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_empty_mobile_is_a_schema_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/admin/auth/otp/request", json={"mobile_number": ""})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["fields"][0]["field"] == "mobile_number"


class _AcceptingService:
    async def request_otp(self, payload, *, purpose=None, channel=None):
        from app.modules.authentication.mobile_number import normalize_mobile_number

        assert normalize_mobile_number(payload.mobile_number) == "+919876500000"
        return OTPRequestResponse(request_id="request-1", expires_in=300, resend_after=30)


@pytest.mark.parametrize("mobile", ["+919876500000", "9876500000", "91 98765 00000"])
def test_valid_mobile_passes_validation(mobile: str) -> None:
    app.dependency_overrides[get_authentication_service] = _AcceptingService
    try:
        response = TestClient(app).post("/api/v1/admin/auth/otp/request", json={"mobile_number": mobile})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202


def test_customer_check_mobile_rejects_invalid_number(client: TestClient) -> None:
    response = client.post("/api/v1/customer/auth/check-mobile", json={"mobile_number": "0000000001"})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_MOBILE_NUMBER"
