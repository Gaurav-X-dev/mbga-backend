"""Customer display codes: `MBGA-R-0001`, `MBGA-I-0002` (spec §3.6).

The code is what staff read out on the phone and search by. It is **not** an authorisation
token — nothing is ever loaded by code alone without the merchant scope also being applied,
because codes are sequential and therefore guessable by design.

Allocation is concurrency-safe. Two staff members registering customers at the same instant
must not both be handed `0007`; the counter row is locked for the moment it is incremented,
which serialises just those two statements.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.constants import CustomerType
from app.modules.customers.models import CustomerCodeSequence

CODE_PREFIX = "MBGA"
TYPE_LETTERS: dict[CustomerType, str] = {
    CustomerType.RETAIL: "R",
    CustomerType.INDUSTRIAL: "I",
}
# Four digits keeps the printed code short. It widens past 9999 rather than wrapping, so the
# format stays sortable and never collides.
PAD_WIDTH = 4


def format_code(customer_type: CustomerType, value: int) -> str:
    return f"{CODE_PREFIX}-{TYPE_LETTERS[customer_type]}-{value:0{PAD_WIDTH}d}"


class CustomerCodeAllocator:
    """Hands out the next code for a customer type."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def allocate(self, customer_type: CustomerType) -> str:
        """Reserve the next code. Must be called inside the caller's transaction.

        The reservation commits or rolls back with the customer row, so a failed
        registration does not burn a number — and a successful one cannot reuse it.
        """
        prefix = f"{CODE_PREFIX}-{TYPE_LETTERS[customer_type]}"
        row = await self._locked_sequence(prefix)
        value = row.next_value
        row.next_value = value + 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return format_code(customer_type, value)

    async def _locked_sequence(self, prefix: str) -> CustomerCodeSequence:
        row = await self.session.scalar(
            select(CustomerCodeSequence).where(CustomerCodeSequence.prefix == prefix).with_for_update()
        )
        if row is not None:
            return row
        # First customer of this type. Two concurrent requests can both reach here, so the
        # loser of the insert re-reads the winner's row under the lock rather than failing.
        row = CustomerCodeSequence(prefix=prefix, next_value=1, updated_at=datetime.now(UTC))
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
                select(CustomerCodeSequence).where(CustomerCodeSequence.prefix == prefix).with_for_update()
            )
        return row
