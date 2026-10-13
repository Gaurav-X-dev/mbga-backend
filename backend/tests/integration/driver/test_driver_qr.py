"""The UPI QR a driver shows a customer at the gate.

The endpoint had no test of its own, which is how it shipped asking the app for an `orderId` it
already knew. The app sent something else - an order number rather than an id - and every QR came
back "The orderId does not belong to this delivery", with no way for the driver to take payment.
"""

import pytest
from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip
from app.modules.orders.models import Order

from app.modules.merchants.models import Merchant
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def with_upi(env, slip):
    """Give the slip's merchant the UPI details a QR needs."""
    merchant_id = await env.scalar(
        select(DeliverySlip.merchant_id).where(DeliverySlip.id == slip["id"])
    )
    await env.execute(
        update(Merchant)
        .where(Merchant.id == merchant_id)
        .values(upi_id="mbga@okhdfcbank", upi_payee_name="MBGA Gas Agency")
    )


async def test_a_qr_needs_no_order_id(env):
    """The delivery is in the path and knows its own order; the app repeating it only adds a
    value it can get wrong."""
    _staff, token, slip, _driver = await on_the_road(env)
    await with_upi(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": 1000}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["orderId"] == slip["orderId"]
    assert body["upiString"].startswith("upi://pay?")
    assert "1000.00" in body["upiString"]


async def test_a_matching_order_id_is_still_accepted(env):
    """An app that already sends it keeps working."""
    _staff, token, slip, _driver = await on_the_road(env)
    await with_upi(env, slip)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr",
        token,
        {"orderId": slip["orderId"], "amount": 500},
    )

    assert response.status_code == 200, response.text


async def test_another_deliverys_order_id_is_refused(env):
    """The check that is worth keeping: an app confused about which delivery it is on."""
    _staff_a, token_a, slip_a, _driver_a = await on_the_road(env)
    _staff_b, _token_b, slip_b, _driver_b = await on_the_road(env)
    await with_upi(env, slip_a)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip_a['id']}/generate-qr",
        token_a,
        {"orderId": slip_b["orderId"], "amount": 500},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "QR_ORDER_MISMATCH"


async def test_a_merchant_without_upi_says_so(env):
    """A driver standing at a gate needs to know it is a settings problem, not their phone."""
    _staff, token, slip, _driver = await on_the_road(env)

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": 100}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MERCHANT_UPI_NOT_CONFIGURED"


# --- What the QR may ask for, and what it leaves behind -------------------------------------


async def test_a_qr_cannot_ask_for_more_than_the_delivery_comes_to(env):
    """It used to build a link for any figure at all: a 1,690 delivery could be shown a QR for
    50,000, and the customer's app would display it without a murmur."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await with_upi(env, slip)
    payable = await env.scalar(select(Order.total_amount).where(Order.id == slip["orderId"]))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": payable + 1}
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "QR_AMOUNT_EXCEEDS_PAYABLE"


async def test_the_whole_bill_is_allowed(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await with_upi(env, slip)
    payable = await env.scalar(select(Order.total_amount).where(Order.id == slip["orderId"]))

    response = await env.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": payable}
    )

    assert response.status_code == 200, response.text


async def test_showing_a_qr_leaves_a_trace(env):
    """There is no gateway behind this VPA, so this row is the only evidence the office has
    that a UPI collection was ever asked for."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    await with_upi(env, slip)

    await env.post(f"{DRIVER_DELIVERIES}/{slip['id']}/generate-qr", token, {"amount": 500})

    stored = await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))
    assert stored.qr_amount == 500
    assert stored.qr_generated_at is not None


async def test_a_cash_delivery_has_no_qr_trace(env):
    """Null is the honest answer for a gate where no QR was shown."""
    _staff, _token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    stored = await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))
    assert stored.qr_amount is None
    assert stored.qr_generated_at is None
