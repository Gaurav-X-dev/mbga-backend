"""Fixtures for the delivery slice.

Reuses the authentication suite's database, migration and environment fixtures, the way the
order, pricing, expense and inventory suites do. That conftest is imported here, never edited.

A delivery test needs more setup than most: a confirmed order, stock on the shelf to dispatch it
from, and a driver to assign. `ready_to_dispatch()` assembles the whole chain so the tests
themselves read as the thing under test rather than as fixture plumbing.
"""

from uuid import uuid4

import pytest

from app.modules.customers.models import CustomerProfile
from app.modules.orders.constants import OrderStatus

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
MERCHANT_AUTH = f"{MERCHANT}/auth"
DELIVERIES = f"{MERCHANT}/deliveries"
INVENTORY = f"{MERCHANT}/inventory"
MOVEMENTS = f"{INVENTORY}/movements"
ORDERS = f"{MERCHANT}/orders"

#: Everything the dispatch board needs, plus what it takes to set the scene: place an order,
#: confirm it, put stock on the shelf.
FULL = (
    "delivery.view",
    "delivery.confirm",
    "orders.view",
    "orders.create",
    "orders.cancel",
    "inventory.view",
    "inventory.adjust",
    "pricing.view",
    "pricing.manage",
)
VIEW_ONLY = ("delivery.view", "orders.view", "inventory.view")


@pytest.fixture
def settings_overrides() -> dict:
    """Expose the confirmation code, the way a local deployment does.

    In production the code reaches the customer only through their notification, so a test has no
    way to read it. Turning on the same switch local development already uses lets these tests
    confirm a delivery end to end; `test_code_security.py` covers the production posture, where
    the switch is off and the spec's mock code is refused.
    """
    return {"dev_expose_otp_in_response": True}


async def dispatch_staff(auth_env, merchant=None, permissions: tuple[str, ...] = FULL):
    """Merchant staff holding the delivery permissions. Returns (token, merchant, user)."""
    role = f"dispatch_{uuid4().hex[:8]}"
    await auth_env.create_role(role, "MERCHANT", list(permissions))
    user, merchant = await auth_env.create_merchant_staff(merchant, roles=("manager", role))
    login = await auth_env.sign_in(MERCHANT_AUTH, user.mobile_number)
    return login["token"]["access_token"], merchant, user


async def make_customer(auth_env, merchant, *, customer_type: str = "RETAIL") -> CustomerProfile:
    """An approved, KYC-verified customer of `merchant` with a registered address."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    profile = CustomerProfile(
        id=str(uuid4()),
        merchant_id=merchant.id,
        merchant_code=merchant.code,
        customer_type=customer_type,
        mobile_number=random_mobile(),
        name="Sharma General Store",
        owner_name="Ravi Kumar",
        pricing_tier="STANDARD",
        status="APPROVED",
        kyc_status="VERIFIED",
        address_line1="Shop 14, Sapna Sangeeta Road",
        address_line2="Near Bhawarkua Square",
        address_city="Indore",
        address_state="Madhya Pradesh",
        address_pincode="452001",
        created_at=now,
        updated_at=now,
    )
    async with auth_env.sessions() as db:
        db.add(profile)
        await db.commit()
    return profile


async def price_cylinders(auth_env, merchant, token: str) -> None:
    """Make sure the current month can price what the tests order.

    Reads the pricing months endpoint, which creates the active month on demand, then sets a rate
    for every cylinder through the real route. Orders cannot be placed for an unpriced cylinder,
    and the delivery tests care about vans rather than rate cards.
    """
    months = await auth_env.get(f"{MERCHANT}/pricing/months", token)
    assert months.status_code == 200, months.text
    month_id = months.json()[0]["id"]
    for cylinder in ("LPG_5KG", "LPG_19KG", "LPG_47_5KG_L", "LPG_47_5KG_V", "LPG_422KG_HIPPO"):
        response = await auth_env.client.put(
            f"{MERCHANT}/pricing/months/{month_id}/entries",
            json={"cylinderType": cylinder, "bpclBaseRate": 1500, "tierMarkup": 200},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text


async def refill(auth_env, token: str, cylinder: str = "LPG_19KG", quantity: int = 60) -> None:
    """Put filled cylinders on the shelf, through the real inventory endpoint."""
    response = await auth_env.post(
        MOVEMENTS,
        token,
        {"type": "RECEIVED_FILLED", "cylinderType": cylinder, "quantity": quantity},
    )
    assert response.status_code == 201, response.text


async def place_order(auth_env, token: str, customer_id: str, *lines) -> dict:
    """Place an order and confirm it, so a slip may be raised against it."""
    items = [{"cylinderType": code, "quantity": qty} for code, qty in (lines or (("LPG_19KG", 4),))]
    created = await auth_env.post(
        ORDERS, token, {"customerId": customer_id, "items": items, "orderMode": "NEW"}
    )
    assert created.status_code == 201, created.text
    order = created.json()
    await set_order_status(auth_env, order["id"], OrderStatus.CONFIRMED)
    return order


async def set_order_status(auth_env, order_id: str, status: OrderStatus) -> None:
    """Move an order directly.

    There is no staff endpoint that advances an order through CONFIRMED yet - that is the order
    module's own gap, not the delivery module's - so the tests set the precondition in the table
    rather than pretending an endpoint exists.
    """
    from sqlalchemy import update

    from app.modules.orders.models import Order

    await auth_env.execute(
        update(Order).where(Order.id == order_id).values(status=status.value)
    )


async def make_driver(auth_env, merchant, *, status: str = "ACTIVE", approval: str = "APPROVED"):
    """An approved driver of `merchant`. Returns their user."""
    user, _merchant, _profile = await auth_env.create_delivery_user(
        merchant, status=status, approval_status=approval
    )
    return user


async def ready_to_dispatch(auth_env, *lines, quantity: int = 60, with_driver: bool = True):
    """Staff, customer, priced month, stock, a confirmed order and a scheduled slip.

    Returns `(token, merchant, order, slip, driver)`. This is the state every dispatch test starts
    from, so it is assembled once here rather than six times in the tests.
    """
    token, merchant, _user = await dispatch_staff(auth_env)
    await price_cylinders(auth_env, merchant, token)
    customer = await make_customer(auth_env, merchant)
    for cylinder, _qty in (lines or (("LPG_19KG", 4),)):
        await refill(auth_env, token, cylinder, quantity)
    order = await place_order(auth_env, token, customer.id, *lines)
    driver = await make_driver(auth_env, merchant) if with_driver else None
    body = {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521"}
    if driver is not None:
        body["driverUserId"] = driver.id
    else:
        body["driverName"] = "Hired van driver"
    created = await auth_env.post(DELIVERIES, token, body)
    assert created.status_code == 201, created.text
    return token, merchant, order, created.json(), driver


async def slip_of(auth_env, token: str, slip_id: str) -> dict:
    response = await auth_env.get(f"{DELIVERIES}/{slip_id}", token)
    assert response.status_code == 200, response.text
    return response.json()


async def counts(auth_env, token: str, cylinder: str = "LPG_19KG") -> tuple[int, int, int]:
    """`(filled, empty, damaged)` for one cylinder, off the live snapshot."""
    response = await auth_env.get(INVENTORY, token)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()["items"] if row["cylinderType"] == cylinder)
    return item["filled"], item["empty"], item["damaged"]
