"""Fixtures for the order slice.

Reuses the authentication suite's database, migration and environment fixtures, the way the
customer, pricing and expense suites do. That conftest is imported here, never edited.

Customers are written straight to the table rather than driven through registration and KYC
review: these tests are about ordering, and the registration flow has its own suite. What is
set here is only what §18.2 reads - account status, KYC status and the delivery sites.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.customers.models import CustomerDeliverySite, CustomerProfile

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
CUSTOMER = "/api/v1/customer"
MERCHANT_AUTH = f"{MERCHANT}/auth"
CUSTOMER_AUTH = f"{CUSTOMER}/auth"
ORDERS = f"{MERCHANT}/orders"
CUSTOMER_ORDERS = f"{CUSTOMER}/orders"

STAFF_PERMISSIONS = ("orders.view", "orders.create", "orders.cancel", "pricing.view", "pricing.manage")


@pytest.fixture
def settings_overrides() -> dict:
    """Required by the shared `env` fixture; orders need no setting changed."""
    return {}


async def order_staff(auth_env, merchant=None, permissions: tuple[str, ...] = STAFF_PERMISSIONS):
    """Merchant staff holding the order permissions. Returns (token, merchant, user)."""
    role = f"order_staff_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def make_customer(
    auth_env,
    merchant,
    *,
    customer_type: str = "RETAIL",
    account_status: str = "APPROVED",
    kyc_status: str = "VERIFIED",
    with_site: bool | None = None,
    mobile: str | None = None,
) -> CustomerProfile:
    """A customer of `merchant`, in whatever state the test needs."""
    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()),
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        customer_type=customer_type,
        mobile_number=mobile or random_mobile(),
        name="Apex Foods Pvt Ltd" if customer_type == "INDUSTRIAL" else "Sharma Bakery",
        owner_name="Ravi Kumar",
        pricing_tier="STANDARD",
        status=account_status,
        kyc_status=kyc_status,
        address_line1="12 MG Road",
        address_city="Indore",
        address_state="Madhya Pradesh",
        address_pincode="452001",
        created_at=now,
        updated_at=now,
    )
    async with auth_env.sessions() as db:
        db.add(profile)
        # Flushed before the site: the two are linked by a foreign key but by no ORM
        # relationship, so the unit of work does not order the inserts for us.
        await db.flush()
        # Industrial customers need a site to be eligible at all (spec §18.2), so one is
        # created unless a test is deliberately exercising the "no site" path.
        if with_site is None:
            with_site = customer_type == "INDUSTRIAL"
        if with_site:
            db.add(
                CustomerDeliverySite(
                    id=str(uuid4()),
                    customer_id=profile.id,
                    name="Plant A — Sanwer Road",
                    address_line1="Plot 22, Sector C",
                    address_city="Indore",
                    address_state="Madhya Pradesh",
                    address_pincode="452015",
                    contact_name="Ramesh Patil",
                    contact_mobile="9822001122",
                    is_primary=True,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        await db.commit()
    return profile


async def site_of(auth_env, customer_id: str) -> str:
    from sqlalchemy import select

    site = await auth_env.scalar(
        select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == customer_id)
    )
    assert site is not None, "this customer has no delivery site"
    return site.id


async def customer_token(auth_env, profile: CustomerProfile) -> str:
    """Sign the customer in on their own channel.

    Their `users` row is created here because these customers are inserted directly rather
    than through registration, which is what would normally create it.
    """
    from sqlalchemy import select

    from app.modules.users.models import User

    user = await auth_env.create_user(
        roles=("customer",), mobile=profile.mobile_number, name=profile.owner_name or "Customer"
    )
    async with auth_env.sessions() as db:
        linked = await db.scalar(select(CustomerProfile).where(CustomerProfile.id == profile.id))
        linked.user_id = user.id
        await db.commit()
    assert isinstance(user, User)
    login = await auth_env.sign_in(CUSTOMER_AUTH, profile.mobile_number)
    return login["token"]["access_token"]


async def post(auth_env, path: str, token: str, json: dict | None = None, **headers):
    merged = {"Authorization": f"Bearer {token}", **headers}
    return await auth_env.client.post(path, json=json, headers=merged)


def basket(*lines: tuple[str, int]) -> list[dict]:
    return [{"cylinderType": code, "quantity": quantity} for code, quantity in lines]


async def place_order(auth_env, token: str, customer_id: str, *lines, **overrides):
    """Create one order and return the raw response, so failures can be asserted too."""
    body = {
        "customerId": customer_id,
        "items": basket(*(lines or (("LPG_19KG", 2),))),
        "orderMode": "NEW",
        **overrides,
    }
    return await post(auth_env, ORDERS, token, body)


async def created_order(auth_env, token: str, customer_id: str, *lines, **overrides) -> dict:
    response = await place_order(auth_env, token, customer_id, *lines, **overrides)
    assert response.status_code == 201, response.text
    return response.json()
