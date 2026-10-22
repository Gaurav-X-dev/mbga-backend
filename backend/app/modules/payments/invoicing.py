"""Raising an invoice against a delivered order (spec §10.4).

**When.** At handover, not at dispatch. The spec leaves the choice to the backend, and handover
is the honest moment: until the customer has the cylinders there is nothing to bill for, and a
failed delivery would otherwise leave an invoice for goods that came back on the van.

**Once.** `invoices.order_id` is unique, so a retried confirmation cannot bill a customer twice.
The guard is the constraint rather than a check in the service, because a check that reads then
writes has a window between the two and two confirmations arriving together would both pass it.

**Copied, not joined.** Name, GSTIN and the money are copied off the order and the customer as
they stand now. An invoice is a legal document about a moment; it has to keep saying what was
billed after the customer is renamed or prices are revised.

**Billed for what was handed over.** A part delivery is billed for the cylinders the customer
actually received, not for the ones the order asked for. Billing the order would charge for
cylinders that came back on the van, and the customer would be chasing a credit note for goods
they never had. The lines come from the slip, so the figure the invoice states and the figure
the stock ledger moves are the same count.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_catalogue.service import BusinessCatalogueService
from app.modules.customers.models import CustomerProfile
from app.modules.orders.models import Order, OrderItem
from app.modules.payments.constants import DEFAULT_PAYMENT_TERM_DAYS, InvoiceStatus
from app.modules.payments.invoice_documents import build_issue_snapshot
from app.modules.payments.models import Invoice
from app.modules.payments.numbering import NumberAllocator
from app.shared.money import invoice_gst


async def delivered_total(
    session: AsyncSession, order: Order, delivered: dict[str, int] | None
) -> int:
    """GST-inclusive rupees for the cylinders handed over, at the order's own frozen rates.

    Shared by the invoice and by the driver app's payment check, so the amount a driver is
    allowed to collect at the gate and the amount he is later billing against are worked out by
    the same code. Two implementations of this would drift, and the symptom would be a payment
    refused as over-collection against an invoice the driver had been shown as payable.

    A delivered quantity above what was ordered is capped at the order's: the slip cannot bill
    for more than the customer asked for, whatever the van was loaded with.
    """
    if delivered is None:
        return order.total_amount
    lines = await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    return sum(
        line.unit_price * min(delivered.get(line.cylinder_type, 0), line.quantity)
        for line in lines
    )


class InvoiceRaiser:
    """Turns a delivered order into an invoice, exactly once."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def raise_for(
        self,
        order: Order,
        *,
        delivered: dict[str, int] | None = None,
        now: datetime | None = None,
    ) -> Invoice | None:
        """The invoice for this order, raising it if it does not exist yet.

        Idempotent by design: a second call returns the first invoice rather than a new one, so
        a confirmation that is retried after a timeout bills nothing twice. Runs inside the
        caller's transaction, so the invoice commits or rolls back with the delivery it belongs
        to - an invoice for a handover that did not finish recording would be worse than none.

        `delivered` is what changed hands, by cylinder type. Passing it bills those cylinders
        rather than the order's; leaving it out bills the order whole, which is right for the
        office's own confirmation, where no per-line count was ever taken.

        Returns `None` when nothing was handed over. A handover of nothing is not a zero
        invoice - a zero invoice is a document saying the customer owes nothing, which would sit
        in their statement and in every total as though a sale had happened.
        """
        existing = await self._for_order(order.id)
        if existing is not None:
            return existing

        billed = await self._billed(order, delivered)
        if billed is None:
            return None
        total_amount, subtotal, gst_amount = billed
        moment = now or datetime.now(UTC)
        customer = await self.session.get(CustomerProfile, order.customer_id)
        # Numbered in the financial year of the handover, not of the clock: a delivery
        # confirmed just after midnight on 1 April still belongs to March's books.
        number = await NumberAllocator(self.session, self.merchant_id).next_invoice_number(
            on=moment.date()
        )

        customer_type = await BusinessCatalogueService(self.session).require_active_customer_type(
            order.customer_type
        )
        invoice = Invoice(
            id=str(uuid4()),
            invoice_number=number,
            merchant_id=self.merchant_id,
            order_id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=order.customer_name,
            # Priced at the order's own rates, which were frozen when it was placed - never
            # re-priced here, or the customer would be billed a figure they never agreed to.
            # The quantities are the delivered ones; see `_billed`.
            amount=subtotal,
            gst_percent=order.gst_percent,
            gst_amount=gst_amount,
            total_amount=total_amount,
            paid_amount=0,
            balance=total_amount,
            status=InvoiceStatus.UNPAID.value,
            issued_at=moment,
            due_at=moment + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS),
            # An industrial buyer claims input credit, so their document is a tax invoice. The
            # GST split is on both; this decides which one is printed.
            is_gst_invoice=customer_type.requires_gst_invoice,
            gstin=(customer.gst_number if customer else None),
            created_at=moment,
            updated_at=moment,
        )
        # Freeze the full printable document while all related data still represents this
        # handover.  Later customer, merchant, price-card or address edits must never rewrite
        # a tax invoice that was already issued.
        invoice.document_snapshot = json.dumps(
            await build_issue_snapshot(
                self.session,
                invoice=invoice,
                order=order,
                customer=customer,
                delivered=delivered,
            ),
            separators=(",", ":"),
        )
        self.session.add(invoice)

        # Two confirmations arriving together both get past the read above. The unique key on
        # order_id stops the second, and re-reading the winner's row is the right answer - not
        # an error, because the delivery it belongs to did succeed.
        savepoint = await self.session.begin_nested()
        try:
            await self.session.flush()
        except IntegrityError:
            await savepoint.rollback()
            winner = await self._for_order(order.id)
            if winner is None:  # pragma: no cover - the winner's row must exist by now
                raise
            return winner
        await savepoint.commit()

        order.invoice_id = invoice.id
        return invoice

    async def _billed(
        self, order: Order, delivered: dict[str, int] | None
    ) -> tuple[int, int, int] | None:
        """`(total, subtotal, gst)` for what is actually being billed, or `None` for nothing.

        With no delivered counts the order's own split is copied through untouched, so a slip
        the office confirmed bills exactly what it always did.

        With them, each line is priced at the rate the order froze and multiplied by the
        delivered quantity, capped at what was ordered - a driver cannot bill for more than the
        customer asked for, whatever the slip says. GST is split **once** on the final total
        rather than per line, because rounding each line and summing the parts does not
        reconcile, and `GstSplit` refuses a split that does not add back up.
        """
        if delivered is None:
            return order.total_amount, order.subtotal, order.gst_amount

        total = await delivered_total(self.session, order, delivered)
        if total <= 0:
            return None
        split = invoice_gst(total, order.gst_percent)
        return split.total_amount, split.subtotal, split.gst_amount

    async def _for_order(self, order_id: str) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.order_id == order_id))
