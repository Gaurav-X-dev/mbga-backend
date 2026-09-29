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
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.constants import CustomerType
from app.modules.customers.models import CustomerProfile
from app.modules.orders.models import Order
from app.modules.payments.constants import DEFAULT_PAYMENT_TERM_DAYS, InvoiceStatus
from app.modules.payments.models import Invoice
from app.modules.payments.numbering import NumberAllocator


class InvoiceRaiser:
    """Turns a delivered order into an invoice, exactly once."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def raise_for(self, order: Order, *, now: datetime | None = None) -> Invoice:
        """The invoice for this order, raising it if it does not exist yet.

        Idempotent by design: a second call returns the first invoice rather than a new one, so
        a confirmation that is retried after a timeout bills nothing twice. Runs inside the
        caller's transaction, so the invoice commits or rolls back with the delivery it belongs
        to - an invoice for a handover that did not finish recording would be worse than none.
        """
        existing = await self._for_order(order.id)
        if existing is not None:
            return existing

        moment = now or datetime.now(UTC)
        customer = await self.session.get(CustomerProfile, order.customer_id)
        number = await NumberAllocator(self.session, self.merchant_id).next_invoice_number()

        invoice = Invoice(
            id=str(uuid4()),
            invoice_number=number,
            merchant_id=self.merchant_id,
            order_id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=order.customer_name,
            # The order's own split, copied rather than recomputed. Prices were frozen when the
            # order was placed; recalculating here would bill a different number from the one
            # the customer agreed to.
            amount=order.subtotal,
            gst_percent=order.gst_percent,
            gst_amount=order.gst_amount,
            total_amount=order.total_amount,
            paid_amount=0,
            balance=order.total_amount,
            status=InvoiceStatus.UNPAID.value,
            issued_at=moment,
            due_at=moment + timedelta(days=DEFAULT_PAYMENT_TERM_DAYS),
            # An industrial buyer claims input credit, so their document is a tax invoice. The
            # GST split is on both; this decides which one is printed.
            is_gst_invoice=(order.customer_type == CustomerType.INDUSTRIAL.value),
            gstin=(customer.gst_number if customer else None),
            created_at=moment,
            updated_at=moment,
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

    async def _for_order(self, order_id: str) -> Invoice | None:
        return await self.session.scalar(select(Invoice).where(Invoice.order_id == order_id))
