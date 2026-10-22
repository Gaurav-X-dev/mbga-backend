"""Suite-wide configuration.

`FCM_ENABLED` is forced off before anything reads the settings. A developer's `.env` may
well have push switched on, and the auto-dispatch fires on every request that queues a
notification - the suite would then make a real Firebase call per test, which is slow,
flaky and reaches the network from a unit test run. The dispatcher's own behaviour is
covered directly in `tests/integration/notifications` with a stubbed client.

An environment variable rather than an edit to `.env`: pydantic-settings reads the
environment ahead of the file, so this wins without touching anyone's local config.
"""

import json
import os
from pathlib import Path

os.environ["FCM_ENABLED"] = "false"


def _ensure_test_fcm_credentials() -> None:
    """Ensure mock Firebase credential files exist in backend/secrets for clean checkouts.

    Secrets are gitignored to prevent leaking real keys or triggering GitHub Push Protection.
    If the test files are absent, create dummy service account payloads so notification
    routing tests can verify project configuration.
    """
    secrets_dir = Path(__file__).resolve().parents[1] / "secrets"
    expected = {
        "fcm-merchant.json": "mbga-merchant",
        "fcm-customer.json": "mbga-customer",
        "fcm-delivery.json": "mbga-delivery-partner",
        "fcm-service-account.json": "mbga-merchant",
    }
    missing = [f for f in expected if not (secrets_dir / f).exists()]
    if not missing:
        return

    secrets_dir.mkdir(parents=True, exist_ok=True)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    for filename in missing:
        project_id = expected[filename]
        payload = {
            "type": "service_account",
            "project_id": project_id,
            "private_key_id": f"dummy-{project_id}",
            "private_key": private_key_pem,
            "client_email": f"firebase-adminsdk@{project_id}.iam.gserviceaccount.com",
            "client_id": "1234567890",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk%40{project_id}.iam.gserviceaccount.com",
            "universe_domain": "googleapis.com",
        }
        target = secrets_dir / filename
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


_ensure_test_fcm_credentials()

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

