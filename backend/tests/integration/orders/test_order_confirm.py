"""Accepting a placed order (`PLACED` -> `CONFIRMED`).

This step had no route at all, which is how every order ended up stuck at `PLACED` and the
merchant app's "Schedule Delivery" sheet had nothing it could act on: a delivery slip may only be
raised against a confirmed order.

So these tests pin both halves - that confirming works, and that the chain it unblocks runs all
the way to a scheduled van.
"""

import pytest
from sqlalchemy import select

from app.modules.orders.models import Order, OrderStatusHistory
from app.shared.notifications.models import NotificationOutbox
from tests.integration.orders.conftest import (
    CUSTOMER_ORDERS,
    ORDERS,
    code_of,
    created_order,
    customer_token,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

STAFF_PERMISSIONS = ("orders.view", "orders.create", "orders.update", "orders.cancel", "pricing.view", "pricing.manage")


async def confirm(env, token: str, order_id: str):
    return await post(env, f"{ORDERS}/{order_id}/confirm", token)


async def status_of(env, order_id: str) -> str:
    return await env.scalar(select(Order.status).where(Order.id == order_id))


async def trail(env, order_id: str) -> list[tuple[str, str | None, str | None]]:
    rows = list(
        await env.execute(
            select(
                OrderStatusHistory.status,
                OrderStatusHistory.changed_by_name,
                OrderStatusHistory.note,
            )
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id)
        )
    )
    return [(r.status, r.changed_by_name, r.note) for r in rows]


async def notifications_for(env, recipient_id: str) -> list[tuple[str, str]]:
    rows = list(
        await env.execute(
            select(NotificationOutbox.event_type, NotificationOutbox.body).where(
                NotificationOutbox.recipient_id == recipient_id
            )
        )
    )
    return [(r.event_type, r.body) for r in rows]


# --- The happy path ------------------------------------------------------------------------------


async def test_a_placed_order_can_be_confirmed(env):
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    assert order["status"] == "PLACED", "precondition"

    response = await confirm(env, token, order["id"])

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONFIRMED"
    assert await status_of(env, order["id"]) == "CONFIRMED"


async def test_the_trail_records_who_confirmed_it(env):
    """From the session, never from the body - and it is what the timeline shows."""
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    await confirm(env, token, order["id"])

    statuses = [(status, by) for status, by, _note in await trail(env, order["id"])]
    assert ("CONFIRMED", "Test Manager") in statuses


async def test_the_trail_carries_the_delivery_date(env):
    """The single most useful thing a customer reads on that line: when the van comes.

    The day, not a slot. The platform stopped promising a morning or afternoon window because the
    godown never scheduled against one.
    """
    from datetime import date

    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    await confirm(env, token, order["id"])

    notes = [note for status, _by, note in await trail(env, order["id"]) if status == "CONFIRMED"]
    expected = date.fromisoformat(order["cutoff"]["scheduledDeliveryDate"])
    assert notes[0] == f"Expected delivery: {expected:%d %b %Y}"


async def test_the_customer_is_told(env):
    """"Confirmed" is the first sign a human has looked at their order."""
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    await confirm(env, token, order["id"])

    events = await notifications_for(env, customer.id)
    confirmed = [body for event, body in events if event == "ORDER_CONFIRMED"]
    assert confirmed, "the customer heard nothing"
    assert order["cutoff"]["scheduledDeliveryDate"] in confirmed[0]


# --- What may not be confirmed ---------------------------------------------------------------------


async def test_an_order_cannot_be_confirmed_twice(env):
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    await confirm(env, token, order["id"])

    again = await confirm(env, token, order["id"])

    assert again.status_code == 200, "idempotent: already there, so nothing to do"
    assert len([s for s, _b, _n in await trail(env, order["id"]) if s == "CONFIRMED"]) == 1


async def test_a_cancelled_order_cannot_be_confirmed(env):
    """Otherwise a confirmation resurrects an order the customer already called off."""
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    cancelled = await post(env, f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Customer called"})
    assert cancelled.status_code == 200, cancelled.text

    response = await confirm(env, token, order["id"])

    assert response.status_code == 409
    assert code_of(response) == "INVALID_ORDER_STATUS"
    assert await status_of(env, order["id"]) == "CANCELLED"


async def test_another_merchants_order_is_a_404(env):
    theirs_token, theirs_merchant, _u1 = await order_staff(env, permissions=STAFF_PERMISSIONS)
    theirs_customer = await make_customer(env, theirs_merchant)
    theirs = await created_order(env, theirs_token, theirs_customer.id)
    mine_token, _mine, _u2 = await order_staff(env, permissions=STAFF_PERMISSIONS)

    response = await confirm(env, mine_token, theirs["id"])

    assert response.status_code == 404
    assert await status_of(env, theirs["id"]) == "PLACED", "untouched"


# --- Who may confirm -----------------------------------------------------------------------------


async def test_confirming_needs_the_update_permission(env):
    """Placing an order and accepting one are different rights."""
    token, _merchant, _user = await order_staff(env, permissions=("orders.view", "orders.create"))
    merchant_customer = await make_customer(env, _merchant)
    order = await created_order(env, token, merchant_customer.id)

    response = await confirm(env, token, order["id"])

    assert response.status_code == 403
    assert code_of(response) == "PERMISSION_DENIED"


async def test_a_customer_cannot_confirm_their_own_order(env):
    """The step means the merchant has the stock and will deliver. A customer saying so is noise.

    The route is not mounted on the customer channel at all, so this is a 404 rather than a 403.
    """
    token, merchant, _user = await order_staff(env, permissions=STAFF_PERMISSIONS)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    their_token = await customer_token(env, customer)

    response = await post(env, f"{CUSTOMER_ORDERS}/{order['id']}/confirm", their_token)

    assert response.status_code == 404
    assert await status_of(env, order["id"]) == "PLACED"


# --- What it unblocks ------------------------------------------------------------------------------


async def test_confirming_is_what_lets_a_van_be_scheduled(env):
    """The whole point. Before this route existed the dispatch module was unreachable."""
    token, merchant, _user = await order_staff(
        env, permissions=(*STAFF_PERMISSIONS, "delivery.view", "delivery.confirm", "inventory.view", "inventory.adjust")
    )
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    slip_body = {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Ramesh Kumar"}

    refused = await post(env, "/api/v1/merchant/deliveries", token, slip_body)
    await confirm(env, token, order["id"])
    allowed = await post(env, "/api/v1/merchant/deliveries", token, slip_body)

    assert refused.status_code == 409, "a placed order cannot have a van loaded for it"
    assert code_of(refused) == "ORDER_NOT_DISPATCHABLE"
    assert allowed.status_code == 201, allowed.text
    # The order stays CONFIRMED: raising a slip is planning, and nothing has physically happened
    # until the van is dispatched.
    assert await status_of(env, order["id"]) == "CONFIRMED"


async def test_raising_a_slip_tells_the_customer_nothing(env):
    """There is no "preparing" step to announce any more.

    A slip is the office planning a van. The customer hears when it actually leaves, which is the
    first moment anything has happened that concerns them.
    """
    token, merchant, _user = await order_staff(
        env, permissions=(*STAFF_PERMISSIONS, "delivery.view", "delivery.confirm", "inventory.view", "inventory.adjust")
    )
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    await confirm(env, token, order["id"])
    before = [event for event, _body in await notifications_for(env, customer.id)]

    await post(
        env,
        "/api/v1/merchant/deliveries",
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Ramesh Kumar"},
    )

    after = [event for event, _body in await notifications_for(env, customer.id)]
    assert after == before


async def test_the_whole_chain_runs_in_order(env):
    """PLACED -> CONFIRMED -> OUT_FOR_DELIVERY, each step recorded once and in sequence."""
    token, merchant, _user = await order_staff(
        env, permissions=(*STAFF_PERMISSIONS, "delivery.view", "delivery.confirm", "inventory.view", "inventory.adjust")
    )
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    await confirm(env, token, order["id"])
    slip = await post(
        env,
        "/api/v1/merchant/deliveries",
        token,
        {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521", "driverName": "Ramesh Kumar"},
    )
    assert slip.status_code == 201, slip.text
    await post(env, "/api/v1/merchant/inventory/movements", token, {"type": "RECEIVED_FILLED", "cylinderType": "LPG_19KG", "quantity": 20})
    dispatched = await post(env, f"/api/v1/merchant/deliveries/{slip.json()['id']}/dispatch", token)
    assert dispatched.status_code == 200, dispatched.text

    assert [status for status, _by, _note in await trail(env, order["id"])] == [
        "PLACED",
        "CONFIRMED",
        "OUT_FOR_DELIVERY",
    ]
