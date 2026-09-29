"""Fixtures for the notification slice."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.customers.models import CustomerProfile
from app.shared.notifications.models import NotificationOutbox

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

MERCHANT = "/api/v1/merchant/notifications"
CUSTOMER = "/api/v1/customer/notifications"
MERCHANT_AUTH = "/api/v1/merchant/auth"
CUSTOMER_AUTH = "/api/v1/customer/auth"


@pytest.fixture
def settings_overrides() -> dict:
    return {}


async def staff(auth_env, merchant=None, *, fcm_token: str | None = None):
    """Merchant staff, signed in. Returns (token, merchant, user)."""
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager",))
    login = await _sign_in(auth_env, MERCHANT_AUTH, user.mobile_number, fcm_token)
    return login, merchant, user


async def customer(auth_env, merchant, *, fcm_token: str | None = None):
    """An approved customer with a login. Returns (token, profile, user)."""
    now = datetime.now(UTC)
    mobile = random_mobile()
    user = await auth_env.create_user(roles=("customer",), mobile=mobile, name="Ravi Kumar")
    profile = CustomerProfile(
        id=str(uuid4()),
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        user_id=user.id,
        customer_type="RETAIL",
        mobile_number=mobile,
        name="Sharma Bakery",
        owner_name="Ravi Kumar",
        pricing_tier="STANDARD",
        status="APPROVED",
        kyc_status="VERIFIED",
        created_at=now,
        updated_at=now,
    )
    async with auth_env.sessions() as db:
        db.add(profile)
        await db.commit()
    login = await _sign_in(auth_env, CUSTOMER_AUTH, mobile, fcm_token)
    return login, profile, user


async def _sign_in(auth_env, prefix: str, mobile: str, fcm_token: str | None) -> str:
    """Sign in, optionally registering a push token the way the app should."""
    device = {"device_id": f"dev-{uuid4().hex[:8]}", "device_type": "android", "app_version": "1.0.0"}
    if fcm_token:
        device["fcm_token"] = fcm_token
    request = await auth_env.client.post(f"{prefix}/otp/request", json={"mobile_number": mobile, "device": device})
    assert request.status_code == 202, request.text
    verify = await auth_env.client.post(
        f"{prefix}/otp/verify",
        json={
            "request_id": request.json()["request_id"],
            "otp": auth_env.last_code(mobile),
            "device": device,
        },
    )
    assert verify.status_code == 200, verify.text
    return verify.json()["token"]["access_token"]


async def queue(
    auth_env,
    *,
    recipient_kind: str,
    recipient_id: str,
    event_type: str = "ORDER_PLACED",
    entity_type: str = "order",
    entity_id: str | None = None,
    title: str = "Order placed",
    body: str = "Order ORD-2609-0001 has been placed.",
    severity: str = "INFO",
    created_at: datetime | None = None,
) -> str:
    """Queue one outbox row the way a business module would. Returns its id."""
    row_id = str(uuid4())
    async with auth_env.sessions() as db:
        db.add(
            NotificationOutbox(
                id=row_id,
                event_type=event_type,
                recipient_kind=recipient_kind,
                recipient_id=recipient_id,
                entity_type=entity_type,
                entity_id=entity_id or str(uuid4()),
                title=title,
                body=body,
                severity=severity,
                delivered_at=None,
                attempts=0,
                created_at=(created_at or datetime.now(UTC)).replace(tzinfo=None),
            )
        )
        await db.commit()
    return row_id


def minutes_ago(count: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=count)


async def post(auth_env, path: str, token: str, json: dict | None = None):
    return await auth_env.client.post(path, json=json, headers={"Authorization": f"Bearer {token}"})
