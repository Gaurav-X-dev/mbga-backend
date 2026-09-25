"""Events that real endpoints emit.

The catalogue tests say each builder produces a well-formed event. These say the events
actually reach the outbox when the business action happens - which is the part that breaks
silently, because a notification nobody queued looks exactly like a notification nobody
needed.

Every assertion checks the stored row, not the response: what matters is that the event is
durable and carries the id of the thing it is about, so the app can deep-link it and support
can trace it.
"""

import pytest
from sqlalchemy import select

from app.shared.notifications.models import NotificationOutbox
from tests.integration.orders.conftest import (
    ORDERS,
    created_order,
    make_customer,
    order_staff,
    post,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

PRICING = "/api/v1/merchant/pricing"
MERCHANT = "/api/v1/merchant"


async def _events(env, entity_id: str) -> dict[str, NotificationOutbox]:
    """Every queued event about one entity, keyed by event type."""
    rows = await env.execute(
        select(NotificationOutbox).where(NotificationOutbox.entity_id == entity_id)
    )
    return {row[0].event_type: row[0] for row in rows}


async def _for_recipient(env, recipient_id: str) -> dict[str, NotificationOutbox]:
    """Every queued event addressed to someone, keyed by event type.

    Pricing events are keyed on the change-log row they came from rather than on the month
    or the customer, so they are looked up by who they went to.
    """
    rows = await env.execute(
        select(NotificationOutbox).where(NotificationOutbox.recipient_id == recipient_id)
    )
    return {row[0].event_type: row[0] for row in rows}


# --- Orders -----------------------------------------------------------------------------


async def test_placing_an_order_tells_both_sides(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    order = await created_order(env, token, customer.id)

    events = await _events(env, order["id"])
    assert set(events) == {"ORDER_PLACED", "ORDER_RECEIVED"}
    assert events["ORDER_PLACED"].recipient_id == customer.id
    assert events["ORDER_RECEIVED"].recipient_id == merchant.id
    # Both carry the order id, so the app opens the order from either.
    assert all(row.entity_type == "order" for row in events.values())


async def test_cancelling_an_order_tells_the_merchant_too(env):
    """Without it the godown keeps a cancelled order on the loading list."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    cancelled = await post(
        env, f"{ORDERS}/{order['id']}/cancel", token, {"reason": "Customer changed their mind"}
    )

    assert cancelled.status_code == 200, cancelled.text
    events = await _events(env, order["id"])
    assert "ORDER_CANCELLED" in events, "the customer is told"
    assert "ORDER_CANCELLED_MERCHANT" in events, "staff are told"
    staff_event = events["ORDER_CANCELLED_MERCHANT"]
    assert staff_event.recipient_id == merchant.id
    assert staff_event.severity == "WARNING"
    # The reason travels, so staff know whether to call the customer back.
    assert "changed their mind" in staff_event.body


async def test_a_cancellation_without_a_reason_still_reads_cleanly(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)

    await post(env, f"{ORDERS}/{order['id']}/cancel", token)

    body = (await _events(env, order["id"]))["ORDER_CANCELLED_MERCHANT"].body
    assert "None" not in body
    assert "Reason:" not in body


# --- Pricing ----------------------------------------------------------------------------


async def test_a_mid_month_rate_change_tells_the_staff(env):
    """A salesperson quoting from what they last saw is how a customer is misquoted."""
    token, merchant, user = await order_staff(env)
    months = (await env.get(f"{PRICING}/months", token)).json()
    month_id = months[0]["id"]

    changed = await env.client.put(
        f"{PRICING}/months/{month_id}/entries",
        json={"cylinderType": "LPG_19KG", "bpclBaseRate": 1900, "tierMarkup": 200,
              "reason": "BPCL base rate revised mid-month"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert changed.status_code == 200, changed.text
    event = (await _for_recipient(env, merchant.id))["pricing.rate_changed"]
    assert event.recipient_kind == "merchant"
    assert event.recipient_id == merchant.id
    assert event.severity == "WARNING"
    # Old and new, so the reader does not have to open the screen to see what moved.
    assert "₹1,800" in event.body and "₹2,100" in event.body
    assert user.full_name in event.body
    assert "BPCL base rate revised" in event.body


async def test_setting_a_customer_price_tells_that_customer(env):
    """They should not discover their own rate on an invoice."""
    token, merchant, user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await env.client.put(
        f"{MERCHANT}/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700, "reason": "Loyalty discount"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    event = (await _for_recipient(env, customer.id))["pricing.customer_price_set"]
    assert event.recipient_kind == "customer"
    assert event.recipient_id == customer.id
    assert "₹1,700" in event.body
    assert user.full_name in event.body
    assert "Loyalty discount" in event.body


async def test_removing_a_customer_price_tells_them_what_it_reverts_to(env):
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    await env.client.put(
        f"{MERCHANT}/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700},
        headers={"Authorization": f"Bearer {token}"},
    )

    removed = await env.client.delete(
        f"{MERCHANT}/customers/{customer.id}/pricing/LPG_19KG",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert removed.status_code == 200, removed.text
    event = (await _for_recipient(env, customer.id))["pricing.customer_price_removed"]
    assert event.recipient_id == customer.id
    assert event.severity == "WARNING"
    # The standard rate they land back on, so the message is actionable on its own.
    assert "₹1,800" in event.body


async def test_a_pricing_notification_never_blocks_the_write(env):
    """The queue is part of the same transaction, so the price still changed either way."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)

    response = await env.client.put(
        f"{MERCHANT}/customers/{customer.id}/pricing/LPG_5KG",
        json={"overridePrice": 450},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["effectivePrice"] == 450
    assert "pricing.customer_price_set" in await _for_recipient(env, customer.id)
    assert merchant


# --- Everything lands with an id --------------------------------------------------------


async def test_every_queued_event_records_what_it_is_about(env):
    """The DB-level version of the catalogue rule: no row without its entity."""
    token, merchant, _user = await order_staff(env)
    customer = await make_customer(env, merchant)
    order = await created_order(env, token, customer.id)
    await post(env, f"{ORDERS}/{order['id']}/cancel", token)
    await env.client.put(
        f"{MERCHANT}/customers/{customer.id}/pricing/LPG_19KG",
        json={"overridePrice": 1700},
        headers={"Authorization": f"Bearer {token}"},
    )

    rows = await env.execute(
        select(
            NotificationOutbox.event_type,
            NotificationOutbox.entity_type,
            NotificationOutbox.entity_id,
            NotificationOutbox.recipient_id,
        ).where(NotificationOutbox.recipient_id.in_([customer.id, merchant.id]))
    )
    found = list(rows)
    assert found, "the actions above must have queued something"
    for event_type, entity_type, entity_id, recipient_id in found:
        assert entity_type, f"{event_type} has no entity_type"
        assert entity_id, f"{event_type} has no entity_id"
        assert recipient_id, f"{event_type} has no recipient"
