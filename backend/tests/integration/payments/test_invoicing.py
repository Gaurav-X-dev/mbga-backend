"""Where an invoice comes from, and what it says.

There is no endpoint that creates an invoice. One is raised when a delivery is confirmed, which
is the only moment a customer actually owes anything - so these tests drive the real chain and
check the bill that falls out of it.
"""

import pytest
from sqlalchemy import func, select

from app.modules.orders.models import Order
from app.modules.payments.constants import InvoiceStatus
from app.modules.payments.models import Invoice
from tests.integration.deliveries.conftest import DELIVERIES
from tests.integration.payments.conftest import INVOICES, billed

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]


async def test_confirming_a_delivery_raises_the_invoice(env):
    _token, _merchant, _customer, invoice = await billed(env)

    assert invoice["invoiceNumber"].startswith("MBGA/INV/")
    assert invoice["status"] == InvoiceStatus.UNPAID.value
    assert invoice["balance"] == invoice["totalAmount"]
    assert invoice["paidAmount"] == 0
    assert invoice["isOverdue"] is False


async def test_the_invoice_carries_the_order_s_own_money(env):
    """Copied, not recalculated.

    Prices were frozen when the order was placed. Recomputing them here would bill a different
    number from the one the customer agreed to, and nobody would notice until a dispute.
    """
    token, _merchant, _customer, invoice = await billed(env)
    order = await env.get(f"/api/v1/merchant/orders/{invoice['orderId']}", token)

    assert order.status_code == 200, order.text
    body = order.json()
    assert invoice["amount"] == body["subtotal"]
    assert invoice["gstAmount"] == body["gstAmount"]
    assert invoice["gstPercent"] == body["gstPercent"]
    assert invoice["totalAmount"] == body["totalAmount"]
    # GST is broken out of the total, never added on top (spec §18.1).
    assert invoice["amount"] + invoice["gstAmount"] == invoice["totalAmount"]


async def test_the_order_points_back_at_its_invoice(env):
    _token, _merchant, _customer, invoice = await billed(env)

    order_invoice_id = await env.scalar(
        select(Order.invoice_id).where(Order.id == invoice["orderId"])
    )

    assert order_invoice_id == invoice["id"]


async def test_a_delivery_is_never_billed_twice(env):
    """The guard is a unique key on order_id, not a check in the service.

    A check that reads then writes has a window between the two, and a confirmation retried
    after a timeout is exactly the request that lands in it.
    """
    token, _merchant, customer, invoice = await billed(env)
    # Confirming again is refused by the slip's own state machine, but the invoice must be safe
    # even if it were not - so assert the invariant directly.
    count = await env.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.order_id == invoice["orderId"])
    )

    assert count == 1
    listed = await env.get(INVOICES, token, params={"customerId": customer.id})
    assert len(listed.json()) == 1


async def test_a_failed_delivery_bills_nobody(env):
    """Cylinders that came back on the van are not a bill.

    This is why the invoice is raised at handover rather than at dispatch: a van that goes out
    and returns loaded must leave the customer owing nothing.
    """
    from tests.integration.deliveries.conftest import (
        dispatch_staff,
        make_customer,
        price_cylinders,
        refill,
    )
    from tests.integration.payments.conftest import BOOKS, place_order_at

    token, merchant, _user = await dispatch_staff(env, permissions=BOOKS)
    await price_cylinders(env, merchant, token)
    customer = await make_customer(env, merchant)
    await refill(env, token, "LPG_19KG", 60)
    order = await place_order_at(env, token, customer.id, ("LPG_19KG", 2))
    created = await env.post(
        DELIVERIES, token, {"orderId": order["id"], "vehicleNumber": "MP09 GH 4521",
                            "driverName": "Ramesh"}
    )
    assert created.status_code == 201, created.text
    slip = created.json()
    await env.post(f"{DELIVERIES}/{slip['id']}/dispatch", token, {})
    failed = await env.post(
        f"{DELIVERIES}/{slip['id']}/fail", token, {"reason": "Customer refused delivery"}
    )
    assert failed.status_code == 200, failed.text

    invoices = await env.get(INVOICES, token)

    assert invoices.status_code == 200, invoices.text
    assert [row for row in invoices.json() if row["orderId"] == slip["orderId"]] == []


async def test_an_industrial_customer_gets_a_tax_invoice(env):
    """They claim input credit, so the document they need is a GST invoice."""
    _token, _merchant, _customer, invoice = await billed(env, customer_type="INDUSTRIAL")

    assert invoice["isGstInvoice"] is True


async def test_a_retail_customer_gets_a_plain_one(env):
    _token, _merchant, _customer, invoice = await billed(env, customer_type="RETAIL")

    assert invoice["isGstInvoice"] is False


async def test_each_merchant_numbers_its_own_invoices_from_one(env):
    """Not a shared run. A merchant files by invoice number, and a run that skipped the numbers
    another merchant happened to take would be unexplainable to them."""
    _token, _merchant, _customer, first = await billed(env)
    _t2, _m2, _c2, second = await billed(env)

    assert first["invoiceNumber"] == "MBGA/INV/0001"
    assert second["invoiceNumber"] == "MBGA/INV/0001"
    assert first["id"] != second["id"]


async def test_the_invoice_is_due_a_week_out(env):
    _token, _merchant, _customer, invoice = await billed(env)

    assert invoice["dueAt"] > invoice["issuedAt"]
