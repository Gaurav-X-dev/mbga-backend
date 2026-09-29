"""Fixtures for invoices and payments.

An invoice is not created by an endpoint - it is raised when a delivery is confirmed. So these
helpers drive the real chain (order -> slip -> dispatch -> confirm) rather than inserting an
invoice row, which means every payment test is also a test that the delivery module raises the
bill the way it is supposed to.
"""

import pytest

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)
from tests.integration.deliveries.conftest import (  # noqa: F401
    DELIVERIES,
    MERCHANT,
    MERCHANT_AUTH,
    dispatch_staff,
    make_customer,
    place_order,
    price_cylinders,
    ready_to_dispatch,
    refill,
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

INVOICES = f"{MERCHANT}/invoices"
PAYMENTS = f"{MERCHANT}/payments"
CUSTOMER_API = "/api/v1/customer"

#: Everything the dispatch chain needs, plus the payment rights under test.
BOOKS = (
    "delivery.view",
    "delivery.confirm",
    "orders.view",
    "orders.create",
    "orders.cancel",
    "inventory.view",
    "inventory.adjust",
    "pricing.view",
    "pricing.manage",
    "payments.view",
    "payments.collect",
    "payments.reconcile",
    # The customer record carries `runningBalance`, which is now real.
    "customers.view",
)

#: Staff who may look at the books but not touch them.
READ_ONLY = (
    "delivery.view",
    "delivery.confirm",
    "orders.view",
    "orders.create",
    "inventory.view",
    "inventory.adjust",
    "pricing.view",
    "pricing.manage",
    "payments.view",
)


async def add_site(auth_env, customer) -> str:
    """Give a customer a delivery site.

    Spec §18.2: an industrial order carries one, so an industrial customer with none cannot
    have an order placed for them at all - which makes this a precondition for billing them.
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.modules.customers.models import CustomerDeliverySite

    now = datetime.now(UTC)
    site_id = str(uuid4())
    async with auth_env.sessions() as db:
        db.add(
            CustomerDeliverySite(
                id=site_id,
                customer_id=customer.id,
                name="Plant gate",
                address_line1="Plot 7, Sector 3",
                address_city="Indore",
                address_state="Madhya Pradesh",
                address_pincode="452001",
                is_primary=True,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()
    return site_id


async def billed(auth_env, *lines, permissions: tuple[str, ...] = BOOKS, customer_type: str = "RETAIL"):
    """A delivered order with an invoice behind it.

    Returns `(token, merchant, customer, invoice)`. This walks the whole chain because that is
    the only way an invoice comes into existence - there is no endpoint that creates one, by
    design: a bill with no delivery behind it is a bill for nothing.
    """
    token, merchant, _user = await dispatch_staff(auth_env, permissions=permissions)
    await price_cylinders(auth_env, merchant, token)
    customer = await make_customer(auth_env, merchant, customer_type=customer_type)
    # Spec §18.2: an industrial order carries a delivery site, so one has to exist - and be
    # named on the order - before that customer can be billed at all.
    site_id = await add_site(auth_env, customer) if customer_type == "INDUSTRIAL" else None
    for cylinder, _qty in (lines or (("LPG_19KG", 2),)):
        await refill(auth_env, token, cylinder, 60)
    order = await place_order_at(
        auth_env, token, customer.id, *(lines or (("LPG_19KG", 2),)), site_id=site_id
    )

    created = await auth_env.post(
        DELIVERIES, token, {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521",
                            "driverName": "Ramesh"}
    )
    assert created.status_code == 201, created.text
    slip = created.json()
    dispatched = await auth_env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token, {})
    assert dispatched.status_code == 200, dispatched.text
    confirmed = await auth_env.post(
        f"{DELIVERIES}/{slip['id']}/confirm",
        token,
        {"otp": dispatched.json()["devConfirmationCode"], "emptiesCollected": 0},
    )
    assert confirmed.status_code == 200, confirmed.text

    invoices = await auth_env.get(INVOICES, token, params={"customerId": customer.id})
    assert invoices.status_code == 200, invoices.text
    assert invoices.json(), "confirming a delivery should have raised an invoice"
    return token, merchant, customer, invoices.json()[0]


async def pay(auth_env, token: str, invoice: dict, amount: int, mode: str = "CASH", **extra):
    """Record a payment against an invoice."""
    body = {"invoiceId": invoice["id"], "amount": amount, "mode": mode, **extra}
    return await auth_env.post(PAYMENTS, token, body)


async def invoice_now(auth_env, token: str, invoice_id: str) -> dict:
    response = await auth_env.get(f"{INVOICES}/{invoice_id}", token)
    assert response.status_code == 200, response.text
    return response.json()


async def place_order_at(auth_env, token: str, customer_id: str, *lines, site_id: str | None = None):
    """Place and confirm an order, naming a delivery site when the customer needs one."""
    from app.modules.orders.constants import OrderStatus
    from tests.integration.deliveries.conftest import ORDERS, set_order_status

    body = {
        "customerId": customer_id,
        "items": [{"cylinderType": code, "quantity": qty} for code, qty in lines],
        "orderMode": "NEW",
    }
    if site_id:
        body["deliverySiteId"] = site_id
    created = await auth_env.post(ORDERS, token, body)
    assert created.status_code == 201, created.text
    order = created.json()
    await set_order_status(auth_env, order["id"], OrderStatus.CONFIRMED)
    return order
