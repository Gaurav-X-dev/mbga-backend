"""Slip numbers: `DS-0148` (spec §3.12).

`DS-<NNNN>`, counted per merchant and never reset. Two merchants both number their own slips
from 1 rather than interleaving into a shared run, because a slip number is something a
merchant's own staff read out over the phone and file the paper copy by.

No month segment, unlike order numbers: the spec's slip id is `DS-0148`, and a continuous run
is what makes it useful as a filing reference. It widens past 9999 rather than wrapping, so it
stays sortable and can never collide.

Allocation copies `orders/numbering.py` deliberately, down to the savepoint on the first
insert: the counter row is locked for the instant it is incremented, which serialises only the
two concurrent slips that actually collide.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.models import DeliveryNumberSequence

PREFIX = "DS"
#: Four digits keeps the printed number short.
PAD_WIDTH = 4


def format_number(value: int) -> str:
    """`DS-0148` for slip 148."""
    return f"{PREFIX}-{value:0{PAD_WIDTH}d}"


class SlipNumberAllocator:
    """Hands out the next slip number for one merchant."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def allocate(self) -> str:
        """Reserve the next number. Must run inside the caller's transaction.

        The reservation commits or rolls back with the slip, so a failed creation does not burn
        a number and a successful one cannot reuse it.
        """
        prefix = f"{PREFIX}-{self.merchant_id}"
        row = await self._locked_sequence(prefix)
        value = row.next_value
        row.next_value = value + 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return format_number(value)

    async def _locked_sequence(self, prefix: str) -> DeliveryNumberSequence:
        row = await self._select_for_update(prefix)
        if row is not None:
            return row
        # This merchant's first slip. Two concurrent creations can both reach here, so the
        # loser of the insert re-reads the winner's row under the lock rather than failing.
        row = DeliveryNumberSequence(
            prefix=prefix,
            next_value=1,
            is_active=True,
            updated_at=datetime.now(UTC),
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # The savepoint rollback usually detaches it, but not always; expunging a row that
            # is already gone raises, so the membership test is not optional.
            if row in self.session:
                self.session.expunge(row)
            existing = await self._select_for_update(prefix)
            assert existing is not None, "the primary key fired, so the row is there"
            return existing
        return row

    async def _select_for_update(self, prefix: str) -> DeliveryNumberSequence | None:
        return await self.session.scalar(
            select(DeliveryNumberSequence)
            .where(DeliveryNumberSequence.prefix == prefix)
            .with_for_update()
        )
