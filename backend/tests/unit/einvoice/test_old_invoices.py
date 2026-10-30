"""What the panel offers for an invoice raised before any of this existed.

The platform has months of invoices that were never queued, because the queue did not exist
when they were raised - and, since this morning, months more that were skipped because the
queueing rule asked about the buyer's GSTIN before anything else. The second group is the
one that matters: an unregistered customer billed over fifty thousand rupees should have
carried an e-Way Bill and did not.

Those invoices are filed by pressing File now on the invoice screen, which is `requeue`.
This pins what the screen offers for each kind, because getting it wrong is either an
invoice nobody can file or a button that asks the portal for something it will refuse.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.einvoice.constants import EInvoiceStatus
from app.modules.einvoice.service import einvoice_view

pytestmark = [pytest.mark.unit]


def invoice(**overrides):
    base = {
        "id": "invoice-1",
        "merchant_id": "merchant-1",
        "invoice_number": "MBGA/26-27/0051",
        "gstin": None,
        "total_amount": 63_000,
        "irn": None,
        "acknowledgement_number": None,
        "eway_bill_number": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def session_with(job):
    return SimpleNamespace(scalar=AsyncMock(return_value=job))


def job(**overrides):
    base = {
        "status": EInvoiceStatus.PENDING.value,
        "with_eway_bill": True,
        "with_irn": False,
        "attempts": 0,
        "last_error": None,
        "next_attempt_at": None,
        "completed_at": None,
        "eway_bill_number": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestAnOldInvoiceNeverQueued:
    @pytest.mark.asyncio
    async def test_an_unregistered_buyer_over_the_threshold_is_offered(self):
        # The invoice this whole change exists for. No job, no GSTIN, over the threshold:
        # the screen must offer to file it, because an e-Way Bill was owed and never raised.
        view = await einvoice_view(session_with(None), invoice())
        assert view.eligible is True
        assert view.with_irn is False
        assert view.with_eway_bill is True
        assert view.status is None
        assert view.can_retry is True

    @pytest.mark.asyncio
    async def test_a_registered_buyer_is_offered_as_before(self):
        view = await einvoice_view(
            session_with(None), invoice(gstin="29AWGPV7107B1Z1", total_amount=10_000)
        )
        assert view.eligible is True
        assert view.with_irn is True
        assert view.with_eway_bill is False
        assert view.can_retry is True

    @pytest.mark.asyncio
    async def test_an_ordinary_domestic_sale_is_not_offered(self):
        # No GSTIN and under the threshold: nothing was ever owed, and offering a button
        # here would send staff to the portal for a document it does not want.
        view = await einvoice_view(session_with(None), invoice(total_amount=1_200))
        assert view.eligible is False
        assert view.can_retry is False

    @pytest.mark.asyncio
    async def test_exactly_fifty_thousand_is_not_offered(self):
        view = await einvoice_view(session_with(None), invoice(total_amount=50_000))
        assert view.eligible is False
        assert view.can_retry is False


class TestAnInvoiceAlreadySettled:
    @pytest.mark.asyncio
    async def test_an_eway_only_job_that_has_its_number_is_done(self):
        # Settled by the bill, not by an IRN it can never have. Offering Retry here would
        # ask the portal for a second bill against one document.
        settled = job(status=EInvoiceStatus.DONE.value, eway_bill_number="121012944976")
        view = await einvoice_view(session_with(settled), invoice())
        assert view.eway_bill_number == "121012944976"
        assert view.can_retry is False

    @pytest.mark.asyncio
    async def test_a_filed_irn_is_not_offered_again(self):
        view = await einvoice_view(
            session_with(job(with_irn=True, status=EInvoiceStatus.DONE.value)),
            invoice(gstin="29AWGPV7107B1Z1", irn="abc123"),
        )
        assert view.can_retry is False


class TestAFailedJob:
    @pytest.mark.asyncio
    async def test_a_rejected_eway_bill_can_be_retried(self):
        rejected = job(
            status=EInvoiceStatus.FAILED.value,
            attempts=1,
            last_error="Pincode does not belong to the state",
        )
        view = await einvoice_view(session_with(rejected), invoice())
        assert view.can_retry is True
        # The portal's own sentence reaches the screen, which is what makes it fixable.
        assert view.last_error == "Pincode does not belong to the state"

    @pytest.mark.asyncio
    async def test_a_queued_job_is_not_offered_while_it_waits(self):
        view = await einvoice_view(session_with(job()), invoice())
        assert view.status == EInvoiceStatus.PENDING.value
        assert view.can_retry is False
