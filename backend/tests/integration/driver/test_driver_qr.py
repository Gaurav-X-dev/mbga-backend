"""The UPI QR a driver shows a customer at the gate.

The endpoint had no test of its own, which is how it shipped asking the app for an `orderId` it
already knew. The app sent something else - an order number rather than an id - and every QR came
back "The orderId does not belong to this delivery", with no way for the driver to take payment.
"""

import pytest
from sqlalchemy import select, update

from app.modules.deliveries.models import DeliverySlip

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
