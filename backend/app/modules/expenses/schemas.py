"""Request and response models for the Expenses screens.

Field names are camelCase, matching the rest of the mobile contract. Amounts go out as JSON
numbers and timestamps as UTC with a `Z` - the same two serializers the pricing module uses,
for the same two reasons: a quoted amount concatenates instead of adding in JS, and a
timestamp with no zone is read as local time and shown hours out.

Ranges are checked in `validation.py`, not by Pydantic constraints, so a bad field comes
back in the coded envelope the app reads.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_number(value: Decimal) -> float:
    return float(value)


def _as_utc(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


Money = Annotated[Decimal, PlainSerializer(_as_number, return_type=float, when_used="json-unless-none")]
UtcTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str, when_used="json-unless-none")]


# --- Categories --------------------------------------------------------------------------


class ExpenseCategoryResponse(BaseModel):
    """One row of the Category sheet."""

    id: str
    code: str
    label: str
    # An `ExpenseIcon` key the app has a drawable for.
    icon: str
    sort_order: int = Field(alias="sortOrder")
    is_active: bool = Field(alias="isActive")
    # False for the seeded starting set. The app can use it to mark what the merchant added.
    is_custom: bool = Field(alias="isCustom")
    # How many expenses reference it. The app can warn before deactivating one in use.
    expense_count: int = Field(default=0, alias="expenseCount")

    model_config = _CAMEL


class CreateExpenseCategoryRequest(BaseModel):
    label: str
    # Generated from the label when omitted, which is the normal case.
    code: str | None = None
    icon: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")

    model_config = _CAMEL


class UpdateExpenseCategoryRequest(BaseModel):
    """Every field optional - this is a partial update.

    `code` is deliberately absent: it is the key historical rows and saved filters were
    written against, so a rename changes the label only.
    """

    label: str | None = None
    icon: str | None = None
    sort_order: int | None = Field(default=None, alias="sortOrder")
    is_active: bool | None = Field(default=None, alias="isActive")

    model_config = _CAMEL


# --- Expenses ----------------------------------------------------------------------------


class ExpenseCategoryBrief(BaseModel):
    """The category as it is embedded in an expense row, so the list needs no second call."""

    id: str
    code: str
    label: str
    icon: str

    model_config = _CAMEL


class ExpenseResponse(BaseModel):
    id: str
    category: ExpenseCategoryBrief
    amount: Money
    note: str | None = None
    # The day the money was spent; `period` is derived from it, server-side. Named
    # `spent_on` in Python because a field literally called `date` shadows `datetime.date`
    # inside the class body and breaks every other date annotation in the module.
    spent_on: date = Field(alias="date")
    period: str
    period_label: str = Field(alias="periodLabel")
    recorded_by: str = Field(alias="recordedBy")
    created_at: UtcTime = Field(alias="createdAt")
    updated_at: UtcTime = Field(alias="updatedAt")

    model_config = _CAMEL


class ExpenseSummary(BaseModel):
    """The header card: total and entry count for the **whole filtered set**, not the page."""

    period: str | None = None
    period_label: str | None = Field(default=None, alias="periodLabel")
    total_amount: Money = Field(alias="totalAmount")
    entry_count: int = Field(alias="entryCount")

    model_config = _CAMEL


class ExpenseListResponse(BaseModel):
    """Paged list plus the summary card above it.

    Carries both paging vocabularies: `page`/`pageSize` for the app, and the
    `total`/`limit`/`offset` the rest of this API uses.
    """

    items: list[ExpenseResponse]
    summary: ExpenseSummary
    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    limit: int
    offset: int

    model_config = _CAMEL


class CreateExpenseRequest(BaseModel):
    """The Add-expense sheet.

    `categoryId` is the normal path (the picker holds ids); `category` accepts a code for a
    caller that only has one. One of the two is required.
    `period` and `recordedBy` are absent on purpose - both are server-derived.
    """

    category_id: str | None = Field(default=None, alias="categoryId")
    category: str | None = None
    amount: Decimal | None = None
    note: str | None = None
    # Defaults to today (server business date) when omitted. Sent by the app as `date`.
    spent_on: date | None = Field(default=None, alias="date")

    model_config = _CAMEL


class UpdateExpenseRequest(BaseModel):
    """Partial update. An omitted field is left alone; `note: ""` clears the note."""

    category_id: str | None = Field(default=None, alias="categoryId")
    category: str | None = None
    amount: Decimal | None = None
    note: str | None = None
    spent_on: date | None = Field(default=None, alias="date")

    model_config = _CAMEL


# --- Periods and breakdown ----------------------------------------------------------------


class ExpensePeriod(BaseModel):
    """One chip in the period row."""

    period: str
    label: str
    total_amount: Money = Field(alias="totalAmount")
    entry_count: int = Field(alias="entryCount")
    is_current: bool = Field(alias="isCurrent")

    model_config = _CAMEL


class ExpenseCategoryTotal(BaseModel):
    category_id: str = Field(alias="categoryId")
    code: str
    label: str
    icon: str
    total_amount: Money = Field(alias="totalAmount")
    entry_count: int = Field(alias="entryCount")
    # Percentage of the period's total, to one decimal. Saves every client doing the maths.
    share_percent: float = Field(alias="sharePercent")

    model_config = _CAMEL


class ExpenseBreakdownResponse(BaseModel):
    period: str | None = None
    period_label: str | None = Field(default=None, alias="periodLabel")
    total_amount: Money = Field(alias="totalAmount")
    entry_count: int = Field(alias="entryCount")
    categories: list[ExpenseCategoryTotal] = Field(default_factory=list)

    model_config = _CAMEL
