"""Expense reads and writes.

Tenancy first: every query starts from the acting merchant, and a category or expense
belonging to another merchant is reported as **404**, never 403 - the same rule the customer
and pricing routes follow, so ids cannot be probed across tenants.

Two things are never taken from a request body: `recordedBy` (it comes from the session) and
`period` (it is derived from the date). Both are the kind of field that looks harmless to
accept and turns a spend report into fiction.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.expenses import validation
from app.modules.expenses.categories import ExpenseCategoryProvisioner
from app.modules.expenses.models import Expense, ExpenseCategory
from app.modules.expenses.schemas import (
    CreateExpenseCategoryRequest,
    CreateExpenseRequest,
    ExpenseBreakdownResponse,
    ExpenseCategoryBrief,
    ExpenseCategoryResponse,
    ExpenseCategoryTotal,
    ExpenseListResponse,
    ExpensePeriod,
    ExpenseResponse,
    ExpenseSummary,
    UpdateExpenseCategoryRequest,
    UpdateExpenseRequest,
)
from app.shared.business.actor import BusinessActor
from app.shared.business.filters import validate_date_range, validate_month
from app.shared.date_time.business_calendar import business_today, month_key, month_key_label
from app.shared.exceptions.api_error import ApiError

#: The period filter value meaning "do not filter" - the app's "All periods" chip.
ALL_PERIODS = "ALL"

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
#: How many period chips the app is offered. A year of history is more than the row scrolls.
MAX_PERIODS = 24


def _not_found(code: str = "NOT_FOUND") -> ApiError:
    return ApiError(code, status.HTTP_404_NOT_FOUND)


@dataclass(frozen=True)
class ExpenseFilters:
    """The list screen's filter row, already parsed."""

    period: str | None = None
    category_id: str | None = None
    category_code: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = None


class ExpenseService:
    """Everything the Expenses screens do, for one acting merchant staff member."""

    def __init__(self, session: AsyncSession, actor: BusinessActor) -> None:
        self.session = session
        self.actor = actor
        self.merchant_id = actor.require_merchant_id()

    # --- Categories --------------------------------------------------------------------

    async def categories(self, *, include_inactive: bool = False) -> list[ExpenseCategoryResponse]:
        """The Category sheet. Seeds the starting set on first touch."""
        await ExpenseCategoryProvisioner(self.session, self.merchant_id).ensure_seeded()
        await self.session.commit()

        statement = select(ExpenseCategory).where(ExpenseCategory.merchant_id == self.merchant_id)
        if not include_inactive:
            statement = statement.where(ExpenseCategory.is_active.is_(True))
        rows = list(
            await self.session.scalars(
                statement.order_by(ExpenseCategory.sort_order, ExpenseCategory.label)
            )
        )
        counts = await self._expense_counts({row.id for row in rows})
        return [_category_view(row, counts.get(row.id, 0)) for row in rows]

    async def create_category(self, payload: CreateExpenseCategoryRequest) -> ExpenseCategoryResponse:
        """Add a category of this merchant's own."""
        await ExpenseCategoryProvisioner(self.session, self.merchant_id).ensure_seeded()

        label = validation.label(payload.label)
        code = validation.category_code(payload.code, fallback=label)
        icon = validation.icon(payload.icon)

        clash = await self.session.scalar(
            select(ExpenseCategory).where(
                ExpenseCategory.merchant_id == self.merchant_id, ExpenseCategory.code == code
            )
        )
        if clash is not None:
            # Names the existing row's label, because the clash is usually a category the
            # merchant deactivated earlier and has forgotten about.
            raise ApiError(
                "CONFLICT",
                status.HTTP_409_CONFLICT,
                f"A category with this code already exists ({clash.label}).",
            )

        now = datetime.now(UTC)
        category = ExpenseCategory(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            code=code,
            label=label,
            icon=icon,
            sort_order=payload.sort_order if payload.sort_order is not None else await self._next_order(),
            is_active=True,
            is_custom=True,
            created_at=now,
            updated_at=now,
        )
        self.session.add(category)
        await self.session.commit()
        return _category_view(category, 0)

    async def update_category(
        self, category_id: str, payload: UpdateExpenseCategoryRequest
    ) -> ExpenseCategoryResponse:
        """Rename, re-icon, reorder or deactivate. The code never moves."""
        category = await self._owned_category(category_id)
        if payload.label is not None:
            category.label = validation.label(payload.label)
        if payload.icon is not None:
            category.icon = validation.icon(payload.icon)
        if payload.sort_order is not None:
            category.sort_order = payload.sort_order
        if payload.is_active is not None:
            category.is_active = payload.is_active
        category.updated_at = datetime.now(UTC)
        await self.session.commit()
        return _category_view(category, (await self._expense_counts({category.id})).get(category.id, 0))

    async def delete_category(self, category_id: str) -> ExpenseCategoryResponse:
        """Remove a category, or deactivate it when history depends on it.

        A category with expenses filed against it is never deleted: the rows would lose the
        label they were reported under. It is deactivated instead, which takes it out of the
        picker and leaves the history readable. An unused one is deleted outright.
        """
        category = await self._owned_category(category_id)
        used = (await self._expense_counts({category.id})).get(category.id, 0)
        if used:
            category.is_active = False
            category.updated_at = datetime.now(UTC)
            await self.session.commit()
            return _category_view(category, used)

        view = _category_view(category, 0)
        await self.session.delete(category)
        await self.session.commit()
        return view

    async def _owned_category(self, category_id: str) -> ExpenseCategory:
        category = await self.session.get(ExpenseCategory, category_id)
        if category is None or category.merchant_id != self.merchant_id:
            raise _not_found("EXPENSE_CATEGORY_NOT_FOUND")
        return category

    async def _next_order(self) -> int:
        highest = await self.session.scalar(
            select(ExpenseCategory.sort_order)
            .where(ExpenseCategory.merchant_id == self.merchant_id)
            .order_by(ExpenseCategory.sort_order.desc())
            .limit(1)
        )
        return 0 if highest is None else highest + 1

    async def _expense_counts(self, category_ids: set[str]) -> dict[str, int]:
        if not category_ids:
            return {}
        rows = await self.session.execute(
            select(Expense.category_id, func.count())
            .where(Expense.merchant_id == self.merchant_id, Expense.category_id.in_(category_ids))
            .group_by(Expense.category_id)
        )
        return {category_id: count for category_id, count in rows}

    # --- Expenses ----------------------------------------------------------------------

    async def list_expenses(
        self, filters: ExpenseFilters, *, page: int, page_size: int, offset: int | None = None
    ) -> ExpenseListResponse:
        """One page of expenses, plus the summary card for the whole filtered set."""
        # Total and count are aggregated over the *same* filtered join as the rows, so the
        # header card and the list can never disagree. The card is the period total, not
        # the page total - that is what the screen shows above a scrolling list.
        totals = (
            await self.session.execute(
                self._filtered(filters, func.coalesce(func.sum(Expense.amount), 0), func.count())
            )
        ).one()
        total_amount, entry_count = Decimal(totals[0]), int(totals[1])

        skip = offset if offset is not None else (page - 1) * page_size
        rows = (
            await self.session.execute(
                self._filtered(filters, Expense, ExpenseCategory)
                .order_by(Expense.spent_on.desc(), Expense.created_at.desc(), Expense.id.desc())
                .limit(page_size)
                .offset(skip)
            )
        ).all()

        period = None if filters.period in (None, ALL_PERIODS) else filters.period
        return ExpenseListResponse(
            items=[_expense_view(expense, category) for expense, category in rows],
            summary=ExpenseSummary(
                period=period,
                period_label=month_key_label(period) if period else None,
                total_amount=total_amount,
                entry_count=entry_count,
            ),
            total=entry_count,
            page=page,
            page_size=page_size,
            limit=page_size,
            offset=skip,
        )

    async def get_expense(self, expense_id: str) -> ExpenseResponse:
        expense, category = await self._owned_expense(expense_id)
        return _expense_view(expense, category)

    async def create_expense(self, payload: CreateExpenseRequest) -> ExpenseResponse:
        """File one spend. `period` and `recordedBy` are derived, never accepted."""
        today = business_today()
        category = await self._resolve_category(payload.category_id, payload.category)
        amount = validation.amount(payload.amount)
        spent_on = validation.spent_on(payload.spent_on, today=today)
        note = validation.note(payload.note)

        now = datetime.now(UTC)
        expense = Expense(
            id=str(uuid4()),
            merchant_id=self.merchant_id,
            category_id=category.id,
            amount=amount,
            note=note,
            spent_on=spent_on,
            period=month_key(spent_on),
            recorded_by_user_id=self.actor.user_id,
            recorded_by_name=self.actor.display_name,
            created_at=now,
            updated_at=now,
        )
        self.session.add(expense)
        await self.session.commit()
        return _expense_view(expense, category)

    async def update_expense(self, expense_id: str, payload: UpdateExpenseRequest) -> ExpenseResponse:
        """Partial update. An omitted field is left alone.

        Moving the date moves the report period with it - the two can never drift apart,
        because the period is always recomputed rather than edited.
        """
        expense, category = await self._owned_expense(expense_id)
        today = business_today()

        if payload.category_id is not None or payload.category is not None:
            category = await self._resolve_category(payload.category_id, payload.category)
            expense.category_id = category.id
        if payload.amount is not None:
            expense.amount = validation.amount(payload.amount)
        if payload.spent_on is not None:
            expense.spent_on = validation.spent_on(payload.spent_on, today=today)
            expense.period = month_key(expense.spent_on)
        if payload.note is not None:
            # An empty string is a deliberate "clear the note", which is why this branch
            # keys off `is not None` rather than truthiness.
            expense.note = validation.note(payload.note)

        expense.updated_at = datetime.now(UTC)
        await self.session.commit()
        return _expense_view(expense, category)

    async def delete_expense(self, expense_id: str) -> None:
        expense, _category = await self._owned_expense(expense_id)
        await self.session.delete(expense)
        await self.session.commit()

    async def _owned_expense(self, expense_id: str) -> tuple[Expense, ExpenseCategory]:
        row = (
            await self.session.execute(
                select(Expense, ExpenseCategory)
                .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
                .where(Expense.id == expense_id, Expense.merchant_id == self.merchant_id)
            )
        ).first()
        if row is None:
            raise _not_found("EXPENSE_NOT_FOUND")
        return row[0], row[1]

    async def _resolve_category(self, category_id: str | None, code: str | None) -> ExpenseCategory:
        """Find the category by id or code, and refuse an inactive one on a write.

        An inactive category is still rendered in history, but nothing new may be filed
        against it - otherwise a category "removed" from the picker keeps collecting rows.
        """
        if not category_id and not code:
            raise validation.invalid("categoryId", "required", "Choose a category.")
        statement = select(ExpenseCategory).where(ExpenseCategory.merchant_id == self.merchant_id)
        statement = (
            statement.where(ExpenseCategory.id == category_id)
            if category_id
            else statement.where(ExpenseCategory.code == str(code).strip().upper())
        )
        category = await self.session.scalar(statement)
        if category is None:
            raise _not_found("EXPENSE_CATEGORY_NOT_FOUND")
        if not category.is_active:
            raise ApiError(
                "CONFLICT",
                status.HTTP_409_CONFLICT,
                f"{category.label} is no longer available. Choose another category.",
            )
        return category

    def _filtered(self, filters: ExpenseFilters, *columns) -> Select:
        """The list query, scoped to the merchant and narrowed by the filter row.

        The caller chooses the columns, so the page and its totals run through this one
        method: `(Expense, ExpenseCategory)` for the rows, `(sum, count)` for the summary
        card. Aggregating over the join directly rather than over a subquery of it also
        avoids the cartesian product an outer `sum(Expense.amount)` would produce.
        """
        statement = (
            select(*columns)
            .select_from(Expense)
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(Expense.merchant_id == self.merchant_id)
        )
        if filters.period and filters.period != ALL_PERIODS:
            statement = statement.where(Expense.period == filters.period)
        if filters.category_id:
            statement = statement.where(Expense.category_id == filters.category_id)
        if filters.category_code:
            statement = statement.where(ExpenseCategory.code == filters.category_code.strip().upper())
        if filters.date_from:
            statement = statement.where(Expense.spent_on >= filters.date_from)
        if filters.date_to:
            statement = statement.where(Expense.spent_on <= filters.date_to)
        if filters.search:
            term = f"%{filters.search.strip()}%"
            statement = statement.where(
                or_(Expense.note.ilike(term), ExpenseCategory.label.ilike(term))
            )
        return statement

    # --- Periods and breakdown ---------------------------------------------------------

    async def periods(self) -> list[ExpensePeriod]:
        """The period chips: every month that has expenses, newest first.

        The current month is always included even when it is still empty, because the Add
        sheet files into it and the screen must have somewhere to show the new row.
        """
        rows = (
            await self.session.execute(
                select(
                    Expense.period,
                    func.coalesce(func.sum(Expense.amount), 0),
                    func.count(),
                )
                .where(Expense.merchant_id == self.merchant_id)
                .group_by(Expense.period)
                .order_by(Expense.period.desc())
                .limit(MAX_PERIODS)
            )
        ).all()

        current = month_key(business_today())
        periods = [
            ExpensePeriod(
                period=period,
                label=month_key_label(period),
                total_amount=Decimal(total),
                entry_count=int(count),
                is_current=period == current,
            )
            for period, total, count in rows
        ]
        if not any(item.period == current for item in periods):
            periods.insert(
                0,
                ExpensePeriod(
                    period=current,
                    label=month_key_label(current),
                    total_amount=Decimal(0),
                    entry_count=0,
                    is_current=True,
                ),
            )
        return periods

    async def breakdown(self, period: str | None) -> ExpenseBreakdownResponse:
        """Category-wise totals for a period - what a spend report reads."""
        conditions = [Expense.merchant_id == self.merchant_id]
        if period and period != ALL_PERIODS:
            conditions.append(Expense.period == period)

        rows = (
            await self.session.execute(
                select(
                    ExpenseCategory.id,
                    ExpenseCategory.code,
                    ExpenseCategory.label,
                    ExpenseCategory.icon,
                    func.coalesce(func.sum(Expense.amount), 0),
                    func.count(),
                )
                .select_from(Expense)
                .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
                .where(and_(*conditions))
                .group_by(ExpenseCategory.id, ExpenseCategory.code, ExpenseCategory.label, ExpenseCategory.icon)
                .order_by(func.sum(Expense.amount).desc())
            )
        ).all()

        total = sum((Decimal(row[4]) for row in rows), Decimal(0))
        entry_count = sum(int(row[5]) for row in rows)
        resolved = None if period in (None, ALL_PERIODS) else period
        return ExpenseBreakdownResponse(
            period=resolved,
            period_label=month_key_label(resolved) if resolved else None,
            total_amount=total,
            entry_count=entry_count,
            categories=[
                ExpenseCategoryTotal(
                    category_id=row[0],
                    code=row[1],
                    label=row[2],
                    icon=row[3],
                    total_amount=Decimal(row[4]),
                    entry_count=int(row[5]),
                    # Guarded because a period whose only rows were deleted mid-request
                    # would otherwise divide by zero.
                    share_percent=round(float(Decimal(row[4]) / total * 100), 1) if total else 0.0,
                )
                for row in rows
            ],
        )


# --- Filter parsing ---------------------------------------------------------------------


def parse_filters(
    *,
    period: str | None,
    category_id: str | None,
    category: str | None,
    date_from: date | None,
    date_to: date | None,
    search: str | None,
) -> ExpenseFilters:
    """Validate the query string before it reaches SQL.

    `period` accepts `YYYY-MM` or the app's `ALL`; anything else is a 422 naming the
    parameter rather than a silently empty list.
    """
    resolved_period = None
    if period and period.strip():
        candidate = period.strip().upper()
        resolved_period = ALL_PERIODS if candidate == ALL_PERIODS else validate_month(period.strip(), field="period")
    # Reuses the shared range rules: both bounds or neither, in order, at most a year.
    validate_date_range(date_from, date_to, start_field="from", end_field="to")
    return ExpenseFilters(
        period=resolved_period,
        category_id=(category_id or "").strip() or None,
        category_code=(category or "").strip() or None,
        date_from=date_from,
        date_to=date_to,
        search=(search or "").strip() or None,
    )


# --- Views --------------------------------------------------------------------------------


def _category_view(row: ExpenseCategory, expense_count: int) -> ExpenseCategoryResponse:
    return ExpenseCategoryResponse(
        id=row.id,
        code=row.code,
        label=row.label,
        icon=row.icon,
        sort_order=row.sort_order,
        is_active=row.is_active,
        is_custom=row.is_custom,
        expense_count=expense_count,
    )


def _expense_view(expense: Expense, category: ExpenseCategory) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        category=ExpenseCategoryBrief(
            id=category.id, code=category.code, label=category.label, icon=category.icon
        ),
        amount=expense.amount,
        note=expense.note,
        spent_on=expense.spent_on,
        period=expense.period,
        period_label=month_key_label(expense.period),
        recorded_by=expense.recorded_by_name,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )
