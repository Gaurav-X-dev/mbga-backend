"""Placing an order (spec §6.4, §18.1, §18.2, §18.4)."""

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.shared.notifications.models import NotificationOutbox
from tests.integration.orders.conftest import (
    ORDERS,
    code_of,
    created_order,
    make_customer,
    order_staff,
    place_order,
    post,
    site_of,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


async def test_an_order_is_placed_with_everything_the_screen_renders(env):
    token, merchant, user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id, ("LPG_19KG", 2), ("LPG_5KG", 1))

    assert order["status"] == "PLACED"
    assert order["orderNumber"].startswith("ORD-")
    assert order["customerName"] == customer.name
    assert order["customerType"] == "RETAIL"
    assert order["totalCylinders"] == 3
    assert order["totalAmount"] == 4090
    assert order["subtotal"] + order["gstAmount"] == order["totalAmount"]
    assert order["orderMode"] == "NEW"
    # Placed from the merchant app, so the staff member's name is on it.
    assert order["source"] == "MERCHANT_APP"
    assert order["createdBy"] == user.full_name
    assert order["placedAt"].endswith("Z")
    assert order["deliverySlot"] in {"09:00 AM – 01:00 PM", "02:00 PM – 06:00 PM"}


async def test_the_status_history_starts_with_the_placement(env):
    token, merchant, user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    assert len(order["statusHistory"]) == 1
    first = order["statusHistory"][0]
    assert first["status"] == "PLACED"
    assert first["by"] == user.full_name
    assert first["at"].endswith("Z")


async def test_the_items_summary_reads_the_way_the_list_shows_it(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)

    order = await created_order(
        env, token, customer.id, ("LPG_47_5KG_L", 6), ("LPG_47_5KG_V", 2), deliverySiteId=site
    )

    assert order["itemsSummary"] == "6 × 47.5 L · 2 × 47.5 V"


async def test_order_numbers_run_in_sequence_within_a_merchant(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    first = await created_order(env, token, customer.id)
    second = await created_order(env, token, customer.id)

    assert first["orderNumber"] != second["orderNumber"]
    assert int(second["orderNumber"][-4:]) == int(first["orderNumber"][-4:]) + 1


async def test_each_merchant_numbers_their_own_orders_from_one(env):
    ours, our_merchant, _u = await order_staff(env)
    theirs, their_merchant, _u2 = await order_staff(env)
    our_customer = await make_customer(env, our_merchant)
    their_customer = await make_customer(env, their_merchant)

    our_order = await created_order(env, ours, our_customer.id)
    their_order = await created_order(env, theirs, their_customer.id)

    # Same readable number, different merchants - which is why `id` is a separate uuid.
    assert our_order["orderNumber"][-4:] == their_order["orderNumber"][-4:] == "0001"
    assert our_order["id"] != their_order["id"]


async def test_the_price_is_frozen_onto_the_line(env):
    """A mid-month rate change must not rewrite what a placed order cost."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id, ("LPG_19KG", 2))
    months = (await env.get("/api/v1/merchant/pricing/months", token)).json()

    changed = await env.client.put(
        f"/api/v1/merchant/pricing/months/{months[0]['id']}/entries",
        json={"cylinderType": "LPG_19KG", "bpclBaseRate": 1900, "tierMarkup": 200},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert changed.status_code == 200, changed.text

    reread = (await env.get(f"{ORDERS}/{order['id']}", token)).json()
    assert reread["items"][0]["unitPrice"] == 1800
    assert reread["totalAmount"] == 3600


async def test_a_customer_override_is_recorded_on_the_line(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await env.client.put(
        f"/api/v1/merchant/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700},
        headers={"Authorization": f"Bearer {token}"},
    )

    order = await created_order(env, token, customer.id, ("LPG_19KG", 1))

    assert order["items"][0]["unitPrice"] == 1700
    line = await env.scalar(select(OrderItem).where(OrderItem.order_id == order["id"]))
    # Recorded so a disputed invoice can be explained without replaying price history.
    assert line.price_overridden is True


async def test_both_notifications_are_queued_on_the_same_transaction(env):
    """Spec §18.8: the customer is told "Order placed", the merchant "New order received"."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    events = list(
        await env.execute(
            select(NotificationOutbox.event_type, NotificationOutbox.recipient_id)
            .where(NotificationOutbox.entity_id == order["id"])
            .order_by(NotificationOutbox.event_type)
        )
    )
    assert [row[0] for row in events] == ["ORDER_PLACED", "ORDER_RECEIVED"]
    assert {row[1] for row in events} == {customer.id, merchant.id}


# --- Industrial rules (§18.2) ----------------------------------------------------------------


async def test_an_industrial_order_carries_its_site_address(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    site = await site_of(env, customer.id)

    order = await created_order(env, token, customer.id, deliverySiteId=site)

    assert order["deliverySiteId"] == site
    assert order["deliverySiteName"] == "Plant A — Sanwer Road"
    assert order["deliveryAddress"]["pincode"] == "452015"


async def test_an_industrial_order_without_a_site_is_refused(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, customer_type="INDUSTRIAL")

    response = await place_order(env, token, customer.id)

    assert response.status_code == 422
    field = response.json()["detail"]["fields"][0]
    assert field["field"] == "deliverySiteId"
    assert field["message"] == "Delivery site is required"


async def test_a_retail_order_falls_back_to_the_registered_address(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    assert order["deliverySiteId"] is None
    assert order["deliverySiteName"] == "Registered delivery address"
    assert order["deliveryAddress"]["city"] == "Indore"


async def test_another_customers_site_cannot_be_used(env):
    token, merchant, _user = await order_staff(env)
    mine = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    other = await make_customer(env, merchant, customer_type="INDUSTRIAL")
    other_site = await site_of(env, other.id)

    response = await place_order(env, token, mine.id, deliverySiteId=other_site)

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "deliverySiteId"


# --- Who may order (§18.2) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account_status", "kyc_status"),
    [
        ("UNDER_REVIEW", "VERIFIED"),
        ("APPROVED", "PENDING"),
        ("REJECTED", "VERIFIED"),
        ("SUSPENDED", "VERIFIED"),
    ],
)
async def test_only_an_approved_verified_customer_may_have_an_order_placed(env, account_status, kyc_status):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant, account_status=account_status, kyc_status=kyc_status)

    response = await place_order(env, token, customer.id)

    assert response.status_code == 403, response.text
    # The reason is the one the eligibility endpoint gives, so the banner and the refusal agree.
    assert response.json()["detail"]["message"]


async def test_a_rejected_order_burns_no_order_number(env):
    """Everything that can refuse runs before anything is written."""
    token, merchant, _user = await order_staff(env)
    blocked = await make_customer(env, merchant, account_status="UNDER_REVIEW")
    good = await make_customer(env, merchant)

    await place_order(env, token, blocked.id)
    order = await created_order(env, token, good.id)

    assert order["orderNumber"].endswith("0001")


# --- Source and actor fields (§1) ----------------------------------------------------------------


async def test_a_source_that_disagrees_with_the_channel_is_refused(env):
    """Spec §1: an actor field must never be trusted from the client."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await place_order(env, token, customer.id, source="CUSTOMER_APP")

    assert response.status_code == 422
    assert response.json()["detail"]["fields"][0]["field"] == "source"


async def test_an_omitted_source_is_derived_from_the_channel(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    assert order["source"] == "MERCHANT_APP"


# --- Idempotency (§1) -----------------------------------------------------------------------------


async def test_the_same_idempotency_key_returns_the_first_order(env):
    """A mobile client that times out and retries must not place a second order."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    body = {"customerId": customer.id, "items": [{"cylinderType": "LPG_19KG", "quantity": 2}], "orderMode": "NEW"}

    first = await post(env, ORDERS, token, body, **{"Idempotency-Key": "retry-abc"})
    second = await post(env, ORDERS, token, body, **{"Idempotency-Key": "retry-abc"})

    assert first.status_code == 201, first.text
    assert second.status_code in (200, 201), second.text
    assert second.json()["id"] == first.json()["id"]
    total = await env.scalar(select(Order).where(Order.customer_id == customer.id))
    assert total is not None
    rows = list(await env.execute(select(Order.id).where(Order.customer_id == customer.id)))
    assert len(rows) == 1


async def test_a_different_key_places_a_second_order(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    body = {"customerId": customer.id, "items": [{"cylinderType": "LPG_19KG", "quantity": 2}], "orderMode": "NEW"}

    first = await post(env, ORDERS, token, body, **{"Idempotency-Key": "key-one"})
    second = await post(env, ORDERS, token, body, **{"Idempotency-Key": "key-two"})

    assert first.json()["id"] != second.json()["id"]


async def test_no_key_still_places_the_order(env):
    """The header is optional; a client that omits it is not punished."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    assert order["status"] == "PLACED"


# --- Permissions -----------------------------------------------------------------------------------


async def test_placing_needs_orders_create(env):
    token, merchant, _user = await order_staff(env, permissions=("orders.view",))
    customer = await make_customer(env, merchant)

    response = await place_order(env, token, customer.id)

    assert response.status_code == 403


async def test_an_order_needs_a_session(env):
    response = await env.client.post(ORDERS, json={"customerId": "x", "items": []})

    assert response.status_code == 401


async def test_a_cylinder_without_a_price_is_a_conflict(env):
    """The basket is legal; the merchant's price card is not complete."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    months = (await env.get("/api/v1/merchant/pricing/months", token)).json()
    from app.modules.pricing.models import PricingEntry

    await env.execute(
        PricingEntry.__table__.delete().where(
            PricingEntry.__table__.c.pricing_month_id == months[0]["id"],
            PricingEntry.__table__.c.cylinder_type == "LPG_5KG",
        )
    )

    response = await place_order(env, token, customer.id, ("LPG_5KG", 1))

    assert response.status_code == 409
    assert code_of(response) == "CYLINDER_NOT_PRICED"


async def test_the_placement_writes_one_history_row_and_its_lines(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id, ("LPG_19KG", 2), ("LPG_5KG", 1))

    lines = list(await env.execute(select(OrderItem.cylinder_type).where(OrderItem.order_id == order["id"])))
    history = list(
        await env.execute(select(OrderStatusHistory.status).where(OrderStatusHistory.order_id == order["id"]))
    )
    assert len(lines) == 2
    assert [row[0] for row in history] == ["PLACED"]
