"""When an industrial order is accepted, what the merchant owes the portal.

An industrial sale is invoiced at confirmation rather than at delivery, so the customer has
the document before the cylinders move. The reference that makes it a legal e-invoice has to
follow the same clock: an invoice number handed over at noon with no IRN behind it until the
van arrives is a document the portal has never seen, and one that is never filed at all if
the delivery is cancelled.

These pin the pairing rather than the mechanics of either side - both `raise_for` and
`queue_for` have their own tests. What is easy to break here is the order of the two, and
whether a retail order or a retried confirmation slips through.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytestmark = [pytest.mark.unit]


class Recorder:
    """Stands in for the two collaborators, remembering what each was asked to do."""

    def __init__(self, invoice=None):
        self.invoice = invoice
        self.raised: list[str] = []
        self.queued: list[object] = []

    def raiser(self, session, merchant_id):
        outer = self

        class _Raiser:
            async def raise_for(self, order, **kwargs):
                outer.raised.append(order.id)
                return outer.invoice

        return _Raiser()

    async def queue_for(self, session, invoice, **kwargs):
        self.queued.append(invoice)
        return SimpleNamespace(id="job-1")


async def run_confirm(monkeypatch, customer_type: str, invoice=None) -> Recorder:
    """Call the helper as confirmation does, with both collaborators replaced."""
    from app.modules.orders import service as orders_service

    recorder = Recorder(invoice)
    monkeypatch.setattr("app.modules.payments.invoicing.InvoiceRaiser", recorder.raiser)
    monkeypatch.setattr("app.modules.einvoice.service.queue_for", recorder.queue_for)

    svc = orders_service.OrderService.__new__(orders_service.OrderService)
    svc.session = AsyncMock()
    svc.merchant_id = "merchant-1"
    order = SimpleNamespace(id="order-1", customer_type=customer_type)
    await svc._raise_industrial_invoice(order)
    return recorder


class TestIndustrial:
    @pytest.mark.asyncio
    async def test_the_invoice_is_raised_and_the_irn_asked_for(self, monkeypatch):
        invoice = SimpleNamespace(id="invoice-1", gstin="29AWGPV7107B1Z1")
        recorder = await run_confirm(monkeypatch, "INDUSTRIAL", invoice)
        assert recorder.raised == ["order-1"]
        assert recorder.queued == [invoice]

    @pytest.mark.asyncio
    async def test_nothing_is_queued_when_no_invoice_was_raised(self, monkeypatch):
        # `raise_for` returns None when there is nothing to bill. Queuing against that would
        # be a job pointing at no document.
        recorder = await run_confirm(monkeypatch, "INDUSTRIAL", None)
        assert recorder.raised == ["order-1"]
        assert recorder.queued == []


class TestRetail:
    @pytest.mark.asyncio
    async def test_a_retail_order_is_left_for_delivery(self, monkeypatch):
        # Retail is invoiced when the handover is confirmed, which is the rule this helper
        # exists to make an exception to.
        recorder = await run_confirm(monkeypatch, "RETAIL", SimpleNamespace(id="invoice-1"))
        assert recorder.raised == []
        assert recorder.queued == []
