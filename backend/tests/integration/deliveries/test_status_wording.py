"""The words the apps put on a screen, decided here rather than in four codebases.

Two things were reported off one screenshot. The deliveries list showed `Dispatched` beside a
bare `ON_LOCATION` - each app was title-casing the raw enum itself, which works for a one-word
code and falls apart on a two-word one. And a bulk confirm of sixteen orders was refused with
"An order that is out for delivery cannot be moved to confirmed", which does not say *which*
of the sixteen to deselect.

Both are the backend's to answer: the status carries its own label, and the refusal carries the
order number.
"""

import pytest
from sqlalchemy import update

from app.modules.deliveries.constants import DeliveryStatus
from app.modules.deliveries.models import DeliverySlip
from tests.integration.deliveries.conftest import (  # noqa: F401 - fixtures
    DELIVERIES,
    ORDERS,
    env,
    place_order,
    ready_to_dispatch,
    settings_overrides,
    slip_of,
)


async def slip_sits_at(env, slip_id: str, status: DeliveryStatus) -> None:
    """Put the slip in a state only the driver app can reach, so the merchant view can be read."""
    async with env.sessions() as db:
        await db.execute(
            update(DeliverySlip).where(DeliverySlip.id == slip_id).values(status=status.value)
        )
        await db.commit()

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


# --- Every slip says what it is called -----------------------------------------------------------


async def test_a_scheduled_slip_carries_its_label(env):
    _token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    assert slip["status"] == DeliveryStatus.SCHEDULED.value
    assert slip["statusLabel"] == "Scheduled"


async def test_the_two_word_status_is_not_left_raw(env):
    """`ON_LOCATION` was reaching the screen exactly like that."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    await slip_sits_at(env, slip["id"], DeliveryStatus.ON_LOCATION)

    showing = await slip_of(env, token, slip["id"])
    assert showing["status"] == DeliveryStatus.ON_LOCATION.value
    assert showing["statusLabel"] == "At Customer"
    assert "_" not in showing["statusLabel"]


async def test_a_dispatched_slip_reads_as_the_customer_is_told(env):
    """The customer's order says "Out for Delivery"; the slip must not say something else."""
    token, _merchant, _order, slip, _driver = await ready_to_dispatch(env)

    await slip_sits_at(env, slip["id"], DeliveryStatus.DISPATCHED)

    assert (await slip_of(env, token, slip["id"]))["statusLabel"] == "Out for Delivery"


async def test_the_list_labels_every_row(env):
    """The screen the report came from reads the list, not the detail."""
    token, _merchant, _order, _slip, _driver = await ready_to_dispatch(env)

    listed = await env.get(DELIVERIES, token)

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert rows, "no slips to check"
    for row in rows:
        assert row.get("statusLabel"), row


# --- A refused bulk confirm names the order --------------------------------------------------------


async def a_refused_bulk_confirm(env):
    """One order already out for delivery, selected alongside a fresh one, as on the screen."""
    token, merchant, out_already, _slip, driver = await ready_to_dispatch(env)
    await env.post(f"{ORDERS}/{out_already['id']}/cancel", token, {"reason": "setting the scene"})
    token, merchant, on_the_road, slip, driver = await ready_to_dispatch(env)
    async with env.sessions() as db:
        from app.modules.orders.constants import OrderStatus
        from app.modules.orders.models import Order

        await db.execute(
            update(Order)
            .where(Order.id == on_the_road["id"])
            .values(status=OrderStatus.OUT_FOR_DELIVERY.value)
        )
        await db.commit()

    refused = await env.post(
        f"{ORDERS}/confirm",
        token,
        {
            "orderIds": [on_the_road["id"]],
            "delivery": {"vehicleNumber": "MP09 GH 4521", "driverName": "Someone else"},
        },
    )
    return on_the_road, refused


async def test_the_refusal_names_the_order(env):
    """Sixteen go in, one is already on a van, and the operator has to find which."""
    order, refused = await a_refused_bulk_confirm(env)

    assert refused.status_code == 409, refused.text
    body = refused.json()["detail"]
    assert body["code"] == "INVALID_ORDER_STATUS"
    assert order["orderNumber"] in body["message"], body["message"]


async def test_the_refusal_says_what_to_do_about_it(env):
    _order, refused = await a_refused_bulk_confirm(env)

    message = refused.json()["detail"]["message"]
    assert "out for delivery" in message.lower(), message
    assert "remove it from the selection" in message.lower(), message
