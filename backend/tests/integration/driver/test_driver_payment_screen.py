"""The delivery app's payment screen, and the cancel screen's reasons.

Two lists and one summary the app used to assemble for itself, each from a different request at
a different moment - so the three figures on the payment screen could disagree with each other,
and the cancel dropdown was a list of strings the app had typed in and the backend had never
heard of.
"""

import pytest
from sqlalchemy import select, update

from app.modules.constants.models import Constant
from app.modules.deliveries.models import DeliverySlip
from app.modules.merchants.models import Merchant
from app.modules.orders.models import Order
from tests.integration.driver.conftest import DRIVER, DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import handover, payable_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

REASONS = "/api/v1/delivery/cancellation-reasons"


async def summary(env, token, slip):
    response = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/payment-summary", token)
    assert response.status_code == 200, response.text
    return response.json()


async def with_upi(env, slip):
    merchant_id = await env.scalar(
        select(DeliverySlip.merchant_id).where(DeliverySlip.id == slip["id"])
    )
    await env.execute(
        update(Merchant)
        .where(Merchant.id == merchant_id)
        .values(upi_id="mbga@okhdfcbank", upi_payee_name="MBGA Gas Agency")
    )


# --- The payment screen ---------------------------------------------------------------------


async def test_the_screen_is_told_what_this_delivery_comes_to(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    body = await summary(env, token, slip)

    assert body["deliveryAmount"] == payable
    assert body["amountPaid"] == 0
    assert body["pendingAmount"] == payable


async def test_the_qr_ceiling_is_this_delivery_alone(env):
    """An old balance is a conversation for the office, not something to collect against a
    cylinder handover - so it is shown beside the figure, never added into it."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    payable = await payable_of(env, slip)

    body = await summary(env, token, slip)

    assert body["maxQrAmount"] == payable


async def test_what_the_customer_already_owed_is_shown(env):
    """Zero used to be hard-coded here, which told a driver at the gate that a customer three
    deliveries behind was square."""
    _staff, token, first, _driver = await on_the_road(env, ("LPG_19KG", 2))
    owed = await payable_of(env, first)
    await handover(env, token, first, [("LPG_19KG", 2)], amount=0)

    body = await summary(env, token, first)

    # Its own invoice is excluded, so the two figures can be added without counting it twice.
    assert body["customerPreviousDue"] == 0
    assert body["pendingAmount"] == owed
    assert body["totalDue"] == owed


async def test_the_screen_knows_whether_upi_is_possible(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    without = await summary(env, token, slip)
    assert without["upiAvailable"] is False
    assert without["upiId"] is None

    await with_upi(env, slip)
    with_it = await summary(env, token, slip)
    assert with_it["upiAvailable"] is True
    assert with_it["upiId"] == "mbga@okhdfcbank"


async def test_the_modes_come_from_the_platform_not_the_app(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    body = await summary(env, token, slip)

    assert sorted(body["modes"]) == ["CASH", "UPI"]


async def test_a_qr_already_shown_is_reported_back(env):
    """So a driver returning to the screen sees what he asked for rather than raising a second."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await with_upi(env, slip)
    await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": 500})

    body = await summary(env, token, slip)

    assert body["lastQrAmount"] == 500
    assert body["lastQrAt"] is not None


async def test_the_previous_due_also_reaches_the_delivery_list(env):
    """Same figure, same screen flow - it was hard-coded to zero there too."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    listed = await env.get(f"{DRIVER_DELIVERIES}/today", token)

    row = [item for item in listed.json() if item["id"] == slip["id"]][0]
    assert row["billing"]["customerPreviousBalance"] == 0


# --- The cancel screen ----------------------------------------------------------------------


async def test_the_reasons_are_served_with_their_rules(env):
    _staff, token, _slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.get(REASONS, token)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["code"] for item in items] == [
        "CUSTOMER_UNAVAILABLE",
        "CUSTOMER_REFUSED",
        "PAYMENT_ISSUE",
        "ADDRESS_UNREACHABLE",
        "OTHER",
        "VEHICLE_BREAKDOWN",
    ]
    assert [item["sortOrder"] for item in items] == [1, 2, 3, 4, 5, 6]
    assert {item["code"] for item in items if item["requiresNotes"]} == {"OTHER"}


async def test_a_reworded_label_is_served(env):
    """A merchant who calls it "Gate locked" should not need a release to say so."""
    _staff, token, _slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await env.execute(
        update(Constant)
        .where(Constant.const_key == "CUSTOMER_UNAVAILABLE")
        .values(const_value="Gate locked")
    )

    items = (await env.get(REASONS, token)).json()["items"]

    assert next(i for i in items if i["code"] == "CUSTOMER_UNAVAILABLE")["label"] == "Gate locked"


async def test_cancelling_with_a_code_writes_its_label(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/cancel",
        token,
        {"reasonCode": "CUSTOMER_UNAVAILABLE"},
    )

    assert response.status_code == 200, response.text
    stored = await env.scalar(
        select(DeliverySlip.failure_reason).where(DeliverySlip.id == slip["id"])
    )
    assert stored == "Customer Unavailable / Shop Closed"


async def test_the_drivers_own_words_are_kept_beside_the_label(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/cancel",
        token,
        {"reasonCode": "CUSTOMER_UNAVAILABLE", "driverNotes": "Shop closed till 6 PM"},
    )

    assert response.status_code == 200, response.text
    stored = await env.scalar(
        select(DeliverySlip.failure_reason).where(DeliverySlip.id == slip["id"])
    )
    assert stored == "Customer Unavailable / Shop Closed - Shop closed till 6 PM"


async def test_other_without_a_note_is_refused(env):
    """"Other" alone is a cancelled delivery nobody can account for afterwards."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/cancel", token, {"reasonCode": "OTHER"}
    )

    assert response.status_code == 422, response.text


async def test_other_with_a_note_is_accepted(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/cancel",
        token,
        {"reasonCode": "OTHER", "driverNotes": "Van broke down at Dewas naka"},
    )

    assert response.status_code == 200, response.text


async def test_free_text_still_works(env):
    """The shipped app sends a typed reason and no code; it must keep working."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/cancel", token, {"reason": "Nobody at the gate"}
    )

    assert response.status_code == 200, response.text


async def test_a_cancel_with_neither_is_refused(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/cancel", token, {})

    assert response.status_code == 422, response.text


async def test_the_reasons_need_a_driver_session(env):
    _staff, _token, _slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    assert (await env.get(REASONS)).status_code == 401
    assert DRIVER
