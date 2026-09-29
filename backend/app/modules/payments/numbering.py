"""Invoice and payment numbers: `MBGA/INV/0144` and `PAY-0211` (spec §3.14, §3.15).

Both are counted per merchant and **never reset**. For payments that is convenience; for
invoices it is the point. An invoice run that restarted monthly would produce two
`MBGA/INV/0001` in one financial year, and a duplicated invoice number is the one thing that
makes a set of books unauditable.

Allocation copies `orders/numbering.py` and `deliveries/numbering.py` deliberately, down to the
savepoint on the first insert: the counter row is locked for the instant it is incremented,
which serialises only the two concurrent writes that actually collide.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import PaymentNumberSequence

INVOICE_PREFIX = "MBGA/INV"
PAYMENT_PREFIX = "PAY"
#: Four digits keeps the printed number short; it widens past 9999 rather than wrapping, so it
#: stays sortable and can never collide.
PAD_WIDTH = 4


def format_invoice_number(value: int) -> str:
    """`MBGA/INV/0144` for invoice 144."""
    return f"{INVOICE_PREFIX}/{value:0{PAD_WIDTH}d}"


def format_payment_number(value: int) -> str:
    """`PAY-0211` for payment 211."""
    return f"{PAYMENT_PREFIX}-{value:0{PAD_WIDTH}d}"


class NumberAllocator:
    """Hands out the next invoice or payment number for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def next_invoice_number(self) -> str:
        return format_invoice_number(await self._next("INV"))

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
