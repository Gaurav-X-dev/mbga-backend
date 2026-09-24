"""Giving a merchant their starting set of expense categories.

There is no "set up your categories" screen - the Add-expense sheet expects the picker to
have something in it the first time it opens. So the starting set is created on first
touch, once per merchant, the same way a pricing month is opened.

It only ever *inserts what is missing by code*. It never rewrites a label, an icon, an order
or an active flag, because after the first run those belong to the merchant: renaming
"Miscellaneous" to "Other" must survive the next request, and deactivating "Rent" must not
bring it back. A merchant who deactivates every seeded category keeps an empty picker, which
is their decision, not a state to repair.
"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.expenses.constants import DEFAULT_CATEGORIES
from app.modules.expenses.models import ExpenseCategory


class ExpenseCategoryProvisioner:
    """Seeds one merchant's category list. Idempotent."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    async def ensure_seeded(self) -> None:
        """Create any missing starting category. The caller commits.

        Two concurrent first-touches race on the `(merchant_id, code)` unique constraint
        rather than producing duplicates.
        """
        existing = set(
            await self.session.scalars(
                select(ExpenseCategory.code).where(ExpenseCategory.merchant_id == self.merchant_id)
            )
        )
        missing = [row for row in DEFAULT_CATEGORIES if row[0] not in existing]
        if not missing:
            return
        now = datetime.now(UTC)
        # Ordered after whatever the merchant already has, so seeding a category that was
        # added to the defaults later does not jump above the merchant's own rows.
        next_order = await self._next_sort_order()
        for offset, (code, label, icon) in enumerate(missing):
            self.session.add(
                ExpenseCategory(
                    id=str(uuid4()),
                    merchant_id=self.merchant_id,
                    code=code,
                    label=label,
                    icon=icon.value,
                    sort_order=next_order + offset,
                    is_active=True,
                    is_custom=False,
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.session.flush()

    async def _next_sort_order(self) -> int:
        highest = await self.session.scalar(
            select(ExpenseCategory.sort_order)
            .where(ExpenseCategory.merchant_id == self.merchant_id)
            .order_by(ExpenseCategory.sort_order.desc())
            .limit(1)
        )
        return 0 if highest is None else highest + 1
