"""Invoice and payment numbers: `MBGA/2026-27/0144` and `PAY-0211` (spec §3.14, §3.15).

An invoice number carries the financial year it belongs to and **restarts at 1 each April**,
which is how an Indian invoice book is actually kept. The year is what keeps that safe: two
invoices may both be `0001`, but never both `MBGA/2026-27/0001`, so the number is still unique
across the books and a duplicate - the one thing that makes a set of books unauditable - is
still impossible.

Payment numbers are counted per merchant and never reset; for them the run is convenience, not
a legal record.

Invoices raised before this format keep the numbers they were printed with. An invoice number
is on paper in somebody's file and is never rewritten.

Allocation copies `orders/numbering.py` and `deliveries/numbering.py` deliberately, down to the
savepoint on the first insert: the counter row is locked for the instant it is incremented,
which serialises only the two concurrent writes that actually collide.
"""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import PaymentNumberSequence
from app.shared.date_time.business_calendar import business_today, financial_year

INVOICE_PREFIX = "MBGA"
PAYMENT_PREFIX = "PAY"
#: Four digits keeps the printed number short; it widens past 9999 rather than wrapping, so it
#: stays sortable and can never collide.
PAD_WIDTH = 4


def format_invoice_number(value: int, year: str) -> str:
    """`MBGA/2026-27/0144` for invoice 144 of 2026-27."""
    return f"{INVOICE_PREFIX}/{year}/{value:0{PAD_WIDTH}d}"


def format_payment_number(value: int) -> str:
    """`PAY-0211` for payment 211."""
    return f"{PAYMENT_PREFIX}-{value:0{PAD_WIDTH}d}"


class NumberAllocator:
    """Hands out the next invoice or payment number for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def next_invoice_number(self, *, on: date | None = None) -> str:
        """The next number in the financial year `on` falls in (default: today).

        The date is the invoice's own, not the clock's: an invoice raised just after midnight
        on 1 April for a delivery made on 31 March belongs to the year that delivery was in.
        """
        year = financial_year(on or business_today())
        # The year is part of the counter's name, which is what makes the run restart: April
        # asks for a sequence that does not exist yet and is handed 1.
        return format_invoice_number(await self._next(f"INV-{year}"), year)

    async def next_payment_number(self) -> str:
        return format_payment_number(await self._next("PAY"))

    async def _next(self, kind: str) -> int:
        """Reserve the next value. Must run inside the caller's transaction.

        The reservation commits or rolls back with the row it numbers, so a failed write does
        not burn a number and a successful one cannot reuse it.
        """
        prefix = f"{kind}-{self.merchant_id}"
        row = await self._locked_sequence(prefix)
        value = row.next_value
        row.next_value = value + 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return value

    async def _locked_sequence(self, prefix: str) -> PaymentNumberSequence:
        row = await self._select_for_update(prefix)
        if row is not None:
            return row
        # This merchant's first invoice or payment. Two concurrent writes can both reach here,
        # so the loser of the insert re-reads the winner's row under the lock rather than
        # failing - a savepoint, so the caller's transaction survives the duplicate key.
        savepoint = await self.session.begin_nested()
        try:
            created = PaymentNumberSequence(
                prefix=prefix, next_value=1, updated_at=datetime.now(UTC)
            )
            self.session.add(created)
            await self.session.flush()
        except IntegrityError:
            await savepoint.rollback()
            row = await self._select_for_update(prefix)
            if row is None:  # pragma: no cover - the winner's row must exist by now
                raise
            return row
        await savepoint.commit()
        return await self._select_for_update(prefix) or created

    async def _select_for_update(self, prefix: str) -> PaymentNumberSequence | None:
        return await self.session.scalar(
            select(PaymentNumberSequence)
            .where(PaymentNumberSequence.prefix == prefix)
            .with_for_update()
        )
