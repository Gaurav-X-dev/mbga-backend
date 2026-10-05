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
    make_driver,
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
    "orders.update",
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
    "orders.update",
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

    driver = await make_driver(auth_env, merchant)
    confirmed_order = await auth_env.post(
        f"{MERCHANT}/orders/{order['id']}/confirm",
        token,
        {
            "delivery": {
                "vehicleNumber": "MP09 GH 4521",
                "driverUserId": driver.id,
            }
        },
    )
    assert confirmed_order.status_code == 200, confirmed_order.text
    slip_response = await auth_env.get(
        f"{DELIVERIES}/{confirmed_order.json()['deliverySlipId']}", token
    )
    assert slip_response.status_code == 200, slip_response.text
    slip = slip_response.json()

    login = await auth_env.sign_in("/api/v1/delivery/auth", driver.mobile_number)
    driver_token = login["token"]["access_token"]
    driver_deliveries = "/api/v1/delivery/deliveries"
    dispatched = await auth_env.post(
        f"{driver_deliveries}/{slip['id']}/out-for-delivery", driver_token, {}
    )
    assert dispatched.status_code == 200, dispatched.text
    counted = await auth_env.post(
        f"{driver_deliveries}/{slip['id']}/confirm",
        driver_token,
        {
            "deliveredItems": [
                {"cylinderType": item["cylinderType"], "quantity": item["quantity"]}
                for item in slip["items"]
            ],
            "collectedEmpties": [],
            "payment": {
                "method": "cash",
                "split": "full",
                "amountCollected": 0,
                "payableAmount": 0,
                "pendingBalance": 0,
            },
        },
    )
    assert counted.status_code == 200, counted.text
    completed = await auth_env.post(
        f"{driver_deliveries}/{slip['id']}/verify-customer-otp",
        driver_token,
        {"otp": dispatched.json()["devConfirmationCode"]},
    )
    assert completed.status_code == 200, completed.text

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
