"""A-13, A-14: environment validation, docs exposure and client IP handling."""

import secrets

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.config.app import Settings
from app.shared.middleware.client_ip import client_ip

pytestmark = pytest.mark.unit

STRONG_SECRET = secrets.token_urlsafe(48)


def _production(**overrides) -> Settings:
    values = {"app_env": "production", "jwt_signing_secret": STRONG_SECRET, "debug": False, "sms_provider": "sms", **overrides}
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    "secret",
    ["change-me-local-only", "secret", "short-but-random-9f3k", "a" * 64, "CHANGE_ME_" + "x" * 40, "replace-with-placeholder-value-000000000"],
)
def test_weak_or_placeholder_signing_secrets_are_rejected_outside_local(secret: str) -> None:
    with pytest.raises(ValidationError) as error:
        _production(jwt_signing_secret=secret)
    message = str(error.value)
    assert "JWT_SIGNING_SECRET" in message
    assert "input_value" not in message
    assert f"'{secret}'" not in message


def test_random_signing_secret_is_accepted_in_production() -> None:
    assert _production().jwt_signing_secret == STRONG_SECRET


@pytest.mark.parametrize("env", ["local", "development", "test"])
def test_local_environments_may_use_the_local_placeholder(env: str) -> None:
    assert Settings(_env_file=None, app_env=env).jwt_signing_secret == "change-me-local-only"


def test_debug_is_rejected_outside_local() -> None:
    with pytest.raises(ValidationError):
        _production(debug=True)


def test_fixed_development_code_is_rejected_outside_local() -> None:
    with pytest.raises(ValidationError):
        _production(dev_fixed_otp_enabled=True, dev_fixed_otp_code="1234")


def test_docs_are_disabled_by_default_outside_local() -> None:
    assert _production().api_docs_enabled is False
    assert Settings(_env_file=None, app_env="development").api_docs_enabled is True
    assert _production(API_DOCS_ENABLED=True).api_docs_enabled is True


def test_production_app_hides_docs_and_sets_security_headers(monkeypatch) -> None:
    from app import main

    monkeypatch.setattr(main, "get_settings", lambda: _production())
    client = TestClient(main.create_app())

    for path in ["/docs", "/redoc", "/openapi.json", "/docs/customer", "/openapi/internal.json"]:
        assert client.get(path).status_code == 404, path
    response = client.get("/health")
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-frame-options"] == "DENY"


def test_unhandled_errors_return_the_envelope_without_details(monkeypatch) -> None:
    from app import main

    monkeypatch.setattr(main, "get_settings", lambda: _production())
    app = main.create_app()

    @app.get("/api/v1/admin/auth/boom")
    async def boom():
        raise RuntimeError("database password is hunter2")

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/admin/auth/boom")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text and "Traceback" not in response.text


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_forwarded_header_is_ignored_from_untrusted_peers() -> None:
    assert client_ip(_request("203.0.113.9", "1.2.3.4"), []) == "203.0.113.9"
    assert client_ip(_request("203.0.113.9", "1.2.3.4"), ["10.0.0.0/8"]) == "203.0.113.9"


def test_forwarded_header_from_trusted_proxy_uses_first_untrusted_hop() -> None:
    trusted = ["10.0.0.0/8", "192.0.2.1"]
    assert client_ip(_request("10.1.2.3", "1.2.3.4, 198.51.100.7, 192.0.2.1"), trusted) == "198.51.100.7"
    assert client_ip(_request("10.1.2.3", "10.0.0.5"), trusted) == "10.1.2.3"
    assert client_ip(_request("10.1.2.3", "not-an-ip"), trusted) == "10.1.2.3"
    assert client_ip(_request("10.1.2.3"), trusted) == "10.1.2.3"


def test_exposing_the_otp_in_the_response_is_rejected_outside_local() -> None:
    with pytest.raises(ValidationError) as error:
        _production(dev_expose_otp_in_response=True)
    assert "DEV_EXPOSE_OTP_IN_RESPONSE" in str(error.value)


@pytest.mark.parametrize("env", ["local", "development", "test"])
def test_exposing_the_otp_in_the_response_is_allowed_locally(env: str) -> None:
    assert Settings(_env_file=None, app_env=env, dev_expose_otp_in_response=True).dev_expose_otp_in_response


def test_the_otp_is_not_exposed_by_default() -> None:
    assert _production().dev_expose_otp_in_response is False
