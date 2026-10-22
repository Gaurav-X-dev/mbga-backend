"""The driver's photo of a payment, and the invoice a part delivery is billed for.

Two things that only became possible once the gate collection was recorded at all. A UPI
payment is a screenshot on a customer's phone until somebody keeps a copy, and an invoice for
four cylinders when two came back on the van is a credit note waiting to be argued about.
"""

import pytest
from sqlalchemy import select

from app.modules.customers.models import CustomerDocument
from app.modules.deliveries.models import DeliverySlip
from app.modules.orders.models import Order
from app.modules.payments.models import Invoice
from tests.integration.customers.conftest import JPEG_BYTES, PDF_BYTES
from tests.integration.driver.conftest import DRIVER_DELIVERIES, on_the_road
from tests.integration.driver.test_driver_payment import confirmation, handover, payable_of

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def upload_proof(env, token, slip, *, content=JPEG_BYTES, filename="upi.jpg", mime="image/jpeg"):
    return await env.client.post(
        f"{DRIVER_DELIVERIES}/{slip['id']}/payment-proof",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content, mime)},
    )


# --- The photo ------------------------------------------------------------------------------


async def test_a_driver_can_photograph_a_payment(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await upload_proof(env, token, slip)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["deliveryId"] == slip["id"]
    assert body["fileId"]
    assert body["contentType"] == "image/jpeg"


async def test_the_photo_is_kept_against_the_delivery(env):
    """So the office reconciling the UPI payment can find the evidence without asking anyone."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    uploaded = (await upload_proof(env, token, slip)).json()

    stored = await env.scalar(select(DeliverySlip).where(DeliverySlip.id == slip["id"]))
    assert stored.payment_proof_file_id == uploaded["fileId"]


async def test_the_photo_belongs_to_the_merchant_not_to_nobody(env):
    """A delivery session carries no merchant scope of its own. Stored without one, the file
    would be unreadable by the only people who need it."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    uploaded = (await upload_proof(env, token, slip)).json()

    document = await env.scalar(
        select(CustomerDocument).where(CustomerDocument.file_id == uploaded["fileId"])
    )
    assert document.merchant_id == (
        await env.scalar(select(DeliverySlip.merchant_id).where(DeliverySlip.id == slip["id"]))
    )
    assert document.document_type == "PAYMENT_PROOF"


async def test_a_pdf_receipt_is_accepted_too(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))

    response = await upload_proof(
        env, token, slip, content=PDF_BYTES, filename="receipt.pdf", mime="application/pdf"
    )

    assert response.status_code == 201, response.text


async def test_another_drivers_delivery_cannot_be_photographed(env):
    """Ownership is the rule on this channel, and it is the slip that carries it."""
    _staff_a, _token_a, slip_a, _driver_a = await on_the_road(env, ("LPG_19KG", 2))
    _staff_b, token_b, _slip_b, _driver_b = await on_the_road(env, ("LPG_19KG", 2))

    response = await upload_proof(env, token_b, slip_a)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DELIVERY_NOT_FOUND"


async def test_the_receipt_carries_the_photo(env):
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 2))
    uploaded = (await upload_proof(env, token, slip)).json()
    payable = await payable_of(env, slip)
    await handover(
        env, token, slip, [("LPG_19KG", 2)], method="UPI", amount=payable, reference="UTR77"
    )

    detail = await env.get(f"{DRIVER_DELIVERIES}/{slip['id']}/completed-detail", token)

    assert detail.json()["payment"]["proofFileId"] == uploaded["fileId"]


# --- The bill for a part delivery -----------------------------------------------------------


async def test_a_part_delivery_is_billed_for_what_was_handed_over(env):
    """Billing the order would charge for cylinders that went back on the van."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 4))
    whole_order = await payable_of(env, slip)

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.total_amount == whole_order // 2
    assert invoice.balance == whole_order // 2


async def test_the_invoice_still_reconciles_to_its_own_gst_split(env):
    """GST is broken out of the total, never added on top, so the parts must add back exactly."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 3))

    await handover(env, token, slip, [("LPG_19KG", 2)], amount=0)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.amount + invoice.gst_amount == invoice.total_amount


async def test_a_full_delivery_is_billed_for_the_whole_order(env):
    """The ordinary case has to stay exactly as it was."""
    _staff, token, slip, _driver = await on_the_road(env, ("LPG_19KG", 3))
    order = await env.scalar(select(Order).where(Order.id == slip["orderId"]))

    await handover(env, token, slip, [("LPG_19KG", 3)], amount=0)

    invoice = await env.scalar(select(Invoice).where(Invoice.order_id == slip["orderId"]))
    assert invoice.total_amount == order.total_amount
    assert invoice.amount == order.subtotal
    assert invoice.gst_amount == order.gst_amount
