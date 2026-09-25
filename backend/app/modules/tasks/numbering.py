"""Readable ids: `TASK-000123`, `MSG-000789`, `ATT-000456` (spec "Data model").

Task numbers are counted **platform-wide** under a row lock, unlike orders and delivery slips
which count per merchant. The difference is which column the readable string is: an order has a
UUID `id` plus an `order_number`, so two merchants can both hold ORD-2609-0001 and the rows still
differ. A task has no second id - the spec's `Task.id` *is* `TASK-000123`, because that is what the
app deep-links on and what the activity lines quote - so a per-merchant counter would give every
merchant a `TASK-000001` and the second one to arrive would collide on the primary key.

The cost is that a merchant's own task ids are not contiguous: their second task might be
TASK-000007. Nobody files paperwork by task number the way they do by order number, so an id the
app can rely on is worth more than a tidy per-merchant run.

Message and attachment ids are **not** sequenced. They are internal handles: nobody reads out a
message id, and a per-merchant counter on them would put a lock on the chattiest write in the
module to produce a string only the database sees. They take the same printed shape so the app's
`id` fields look consistent, with a random suffix rather than a counter.
"""

from datetime import UTC, datetime
from secrets import randbelow

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tasks.models import TaskNumberSequence

TASK_PREFIX = "TASK"
MESSAGE_PREFIX = "MSG"
ATTACHMENT_PREFIX = "ATT"
#: Six digits, matching the spec's examples. It widens past 999999 rather than wrapping.
PAD_WIDTH = 6


def format_task(value: int) -> str:
    """`TASK-000123`."""
    return f"{TASK_PREFIX}-{value:0{PAD_WIDTH}d}"


def new_message_id() -> str:
    """`MSG-4f2a1b`. Random, not sequential - see the module docstring."""
    return f"{MESSAGE_PREFIX}-{randbelow(10**9):09d}"


def new_attachment_id() -> str:
    return f"{ATTACHMENT_PREFIX}-{randbelow(10**9):09d}"


#: The single counter row. One key for the whole platform, because the number it hands out becomes
#: the task's primary key.
SEQUENCE_KEY = TASK_PREFIX


class TaskNumberAllocator:
    """Hands out the next task number. One counter for the platform - see the module docstring."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def allocate(self) -> tuple[int, str]:
        """Reserve the next number, as `(value, "TASK-000123")`.

        Must run inside the caller's transaction, so a failed creation does not burn a number
        and a successful one cannot reuse it.
        """
        row = await self._locked_sequence(SEQUENCE_KEY)
        value = row.next_value
        row.next_value = value + 1
        row.updated_at = datetime.now(UTC)
        await self.session.flush()
        return value, format_task(value)

    async def _locked_sequence(self, prefix: str) -> TaskNumberSequence:
        row = await self._select_for_update(prefix)
        if row is not None:
            return row
        # The platform's first task. Two concurrent creations can both reach here, so the loser
        # of the insert re-reads the winner's row under the lock rather than failing.
        row = TaskNumberSequence(prefix=prefix, next_value=1, updated_at=datetime.now(UTC))
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            if row in self.session:
                self.session.expunge(row)
            existing = await self._select_for_update(prefix)
            assert existing is not None, "the primary key fired, so the row is there"
            return existing
        return row

    async def _select_for_update(self, prefix: str) -> TaskNumberSequence | None:
        return await self.session.scalar(
            select(TaskNumberSequence)
            .where(TaskNumberSequence.prefix == prefix)
            .with_for_update()
        )
