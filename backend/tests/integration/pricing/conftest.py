"""Fixtures for the pricing slice.

Reuses the authentication suite's database, migration and environment fixtures, the way the
customer suite does - there is one migration and seed path for the whole integration suite,
and this package does not edit it.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.customers.models import CustomerProfile

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

MERCHANT = "/api/v1/merchant"
MERCHANT_AUTH = "/api/v1/merchant/auth"
PRICING = f"{MERCHANT}/pricing"


@pytest.fixture
def settings_overrides() -> dict:
    return {}


async def pricing_staff(
    auth_env,
    merchant=None,
    permissions: tuple[str, ...] = ("pricing.view", "pricing.manage", "customers.create", "customers.view"),
):
    """Merchant staff holding the pricing permissions. Returns (token, merchant, user).

    The permissions are granted through a throwaway role rather than by widening `manager`,
    because the seed deliberately leaves pricing unmapped and the RBAC suite asserts that.
    """
    role = f"pricing_staff_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def put(auth_env, path: str, token: str, json: dict | None = None):
    return await auth_env.client.put(path, json=json, headers={"Authorization": f"Bearer {token}"})


async def delete(auth_env, path: str, token: str):
    return await auth_env.client.delete(path, headers={"Authorization": f"Bearer {token}"})


async def current_month(auth_env, token: str) -> dict:
    """The merchant's active pricing month, opened on first read."""
    response = await auth_env.get(f"{PRICING}/months", token)
    assert response.status_code == 200, response.text
    months = response.json()
    assert months, "the current month should be opened on first read"
    return months[0]


def entry_of(month: dict, cylinder_type: str) -> dict:
    return next(entry for entry in month["entries"] if entry["cylinderType"] == cylinder_type)


async def create_customer(auth_env, merchant, *, customer_type: str = "RETAIL") -> str:
    """An approved customer owned by `merchant`.

    Written straight to the table rather than driven through registration and KYC review:
    these tests are about what a customer is *priced* at, and the registration flow has its
    own suite. Only the fields pricing reads are set.
    """
    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()),
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        customer_type=customer_type,
        mobile_number=random_mobile(),
        name="Test Bakery",
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
    return profile.id
