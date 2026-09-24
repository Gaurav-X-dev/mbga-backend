"""Order numbers: `ORD-2609-0151` (spec §1 "IDs", §6.4).

`ORD-<YYMM>-<NNNN>`, restarting each month. The counter is per merchant, so two merchants
on the platform both number their own orders from 1 rather than interleaving into a shared
run - a merchant's order numbers are something their staff read out and file by.

Allocation copies `customers/codes.py` deliberately, down to the savepoint on the first
insert: the counter row is locked for the instant it is incremented, which serialises only
the two concurrent placements that actually collide.
"""

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orders.models import OrderNumberSequence
from app.shared.date_time.business_calendar import business_today

PREFIX = "ORD"
#: Four digits keeps the printed number short. It widens past 9999 rather than wrapping, so
#: the format stays sortable and can never collide inside a month.
PAD_WIDTH = 4


def format_number(day: date, value: int) -> str:
    """`ORD-2609-0151` for September 2026, order 151."""
    return f"{PREFIX}-{day:%y%m}-{value:0{PAD_WIDTH}d}"


class OrderNumberAllocator:
    """Hands out the next order number for one merchant's current month."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def allocate(self, *, day: date | None = None) -> str:
        """Reserve the next number. Must run inside the caller's transaction.

        The reservation commits or rolls back with the order, so a failed placement does
        not burn a number and a successful one cannot reuse it.

        The month comes from the business (IST) date, not UTC: an order placed at 00:30 IST
        on the 1st belongs to the new month's run, which is what the merchant's own books
        will say.
        """
        today = day or business_today()
        prefix = f"{PREFIX}-{self.merchant_id}-{today:%y%m}"
        row = await self._locked_sequence(prefix, today)
        value = row.next_value
        row.next_value = value + 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return format_number(today, value)

    async def _locked_sequence(self, prefix: str, today: date) -> OrderNumberSequence:
        row = await self.session.scalar(
            select(OrderNumberSequence).where(OrderNumberSequence.prefix == prefix).with_for_update()
        )
        if row is not None:
            return row
        # First order of the month for this merchant. Two concurrent placements can both
        # reach here, so the loser of the insert re-reads the winner's row under the lock
        # rather than failing the order.
        row = OrderNumberSequence(
            prefix=prefix,
            next_value=1,
            period=today.replace(day=1),
            updated_at=datetime.now(UTC),
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # The savepoint rollback usually detaches it, but not always; expunging a row
            # that is already gone raises, so the membership test is not optional.
            if row in self.session:
                self.session.expunge(row)
            return await self.session.scalar(
                select(OrderNumberSequence).where(OrderNumberSequence.prefix == prefix).with_for_update()
            )
        return row
