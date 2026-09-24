"""Merchant expense routes - the Expenses list, the Add sheet and the Category picker.

Reads need `expenses.view`, writes need `expenses.manage` - both already seeded in
`roles/seeds.py`. No new permission is introduced, and no role's grants change here;
`scripts/grant_expense_permissions.py` grants them per deployment.

Route order matters in this file: `/expenses/categories` and `/expenses/periods` are
declared before `/expenses/{expense_id}`, otherwise "categories" would be matched as an
expense id and every category request would 404.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.expenses.schemas import (
    CreateExpenseCategoryRequest,
    CreateExpenseRequest,
    ExpenseBreakdownResponse,
    ExpenseCategoryResponse,
    ExpenseListResponse,
    ExpensePeriod,
    ExpenseResponse,
    UpdateExpenseCategoryRequest,
    UpdateExpenseRequest,
)
from app.modules.expenses.service import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ExpenseService,
    parse_filters,
)
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/expenses", tags=["Merchant Expenses"])

MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
CAN_VIEW = Depends(require_permission("expenses.view"))
CAN_MANAGE = Depends(require_permission("expenses.manage"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _service(session: SessionDep, actor: ActorDep) -> ExpenseService:
    return ExpenseService(session, actor)


ServiceDep = Annotated[ExpenseService, Depends(_service)]
CategoryIdPath = Annotated[str, Path(alias="categoryId", max_length=36)]
ExpenseIdPath = Annotated[str, Path(alias="expenseId", max_length=36)]


# --- Categories ---------------------------------------------------------------------------


@router.get(
    "/categories",
    response_model=list[ExpenseCategoryResponse],
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403),
    summary="Expense categories",
)
async def list_expense_categories(
    service: ServiceDep,
    include_inactive: Annotated[
        bool,
        Query(alias="includeInactive", description="Include deactivated categories, for a management screen."),
    ] = False,
) -> list[ExpenseCategoryResponse]:
    """The Category sheet, in display order.

    On a merchant's first call the starting set (Fuel, Vehicle Maintenance, Salary, Rent,
    Utilities, Miscellaneous) is created, so the picker is never empty. After that the list
    is whatever the merchant has configured.
    """
    return await service.categories(include_inactive=include_inactive)


@router.post(
    "/categories",
    response_model=ExpenseCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 409, 422),
    summary="Add an expense category",
)
async def create_expense_category(
    payload: CreateExpenseCategoryRequest, service: ServiceDep
) -> ExpenseCategoryResponse:
    """Add a category of this merchant's own, e.g. "Tolls".

    `code` is generated from the name when omitted ("Godown Repairs" -> `GODOWN_REPAIRS`).
    `icon` must be one the app can draw: fuel, maintenance, salary, rent, utilities, misc.
    """
    return await service.create_category(payload)


@router.patch(
    "/categories/{categoryId}",
    response_model=ExpenseCategoryResponse,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404, 422),
    summary="Update an expense category",
)
async def update_expense_category(
    payload: UpdateExpenseCategoryRequest, service: ServiceDep, category_id: CategoryIdPath
) -> ExpenseCategoryResponse:
    """Rename, re-icon, reorder or deactivate. Every field is optional.

    The `code` cannot be changed: historical rows and saved filters were written against it.
    """
    return await service.update_category(category_id, payload)


@router.delete(
    "/categories/{categoryId}",
    response_model=ExpenseCategoryResponse,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404),
    summary="Remove an expense category",
)
async def delete_expense_category(
    service: ServiceDep, category_id: CategoryIdPath
) -> ExpenseCategoryResponse:
    """Delete the category, or deactivate it if expenses are filed against it.

    The response says which happened: `isActive: false` means it was kept for history and
    taken out of the picker. An unused category is deleted outright.
    """
    return await service.delete_category(category_id)


# --- Periods and breakdown ------------------------------------------------------------------


@router.get(
    "/periods",
    response_model=list[ExpensePeriod],
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403),
    summary="Report periods",
)
async def list_expense_periods(service: ServiceDep) -> list[ExpensePeriod]:
    """The period chips, newest first, each with its own total and entry count.

    The current month is always first even when empty. The app adds its own "All periods"
    chip, which maps to `?period=ALL`.
    """
    return await service.periods()


@router.get(
    "/breakdown",
    response_model=ExpenseBreakdownResponse,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 422),
    summary="Spend by category",
)
async def expense_breakdown(
    service: ServiceDep,
    period: Annotated[str | None, Query(description="`YYYY-MM`, or `ALL` for every period.")] = None,
) -> ExpenseBreakdownResponse:
    """Category-wise totals for one period, biggest first, with each one's share."""
    filters = parse_filters(
        period=period, category_id=None, category=None, date_from=None, date_to=None, search=None
    )
    return await service.breakdown(filters.period)


# --- Expenses -------------------------------------------------------------------------------


@router.get(
    "",
    response_model=ExpenseListResponse,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 422),
    summary="Expenses",
)
async def list_expenses(
    service: ServiceDep,
    period: Annotated[str | None, Query(description="`YYYY-MM`, or `ALL`. Defaults to every period.")] = None,
    category_id: Annotated[str | None, Query(alias="categoryId")] = None,
    category: Annotated[str | None, Query(description="Category code, e.g. FUEL.")] = None,
    date_from: Annotated[date | None, Query(alias="from", description="Earliest spend date.")] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Latest spend date.")] = None,
    search: Annotated[str | None, Query(max_length=120, description="Matches the note or category name.")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE, description="Alias for pageSize.")] = None,
    offset: Annotated[int | None, Query(ge=0, description="Rows to skip, instead of page.")] = None,
) -> ExpenseListResponse:
    """Newest spend first, with the summary card for the **whole filtered set**.

    `summary.totalAmount` and `summary.entryCount` cover every row the filters match, not
    just this page - that is what the header shows above the list.
    """
    filters = parse_filters(
        period=period,
        category_id=category_id,
        category=category,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return await service.list_expenses(
        filters, page=page, page_size=limit or page_size, offset=offset
    )


@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Add an expense",
)
async def create_expense(payload: CreateExpenseRequest, service: ServiceDep) -> ExpenseResponse:
    """File one spend.

    `date` defaults to today and may be back-dated but never post-dated. The report period
    is derived from it, and `recordedBy` comes from the session - neither is read from the
    body.
    """
    return await service.create_expense(payload)


@router.get(
    "/{expenseId}",
    response_model=ExpenseResponse,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 404),
    summary="Expense detail",
)
async def get_expense(service: ServiceDep, expense_id: ExpenseIdPath) -> ExpenseResponse:
    return await service.get_expense(expense_id)


@router.patch(
    "/{expenseId}",
    response_model=ExpenseResponse,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Update an expense",
)
async def update_expense(
    payload: UpdateExpenseRequest, service: ServiceDep, expense_id: ExpenseIdPath
) -> ExpenseResponse:
    """Partial update - an omitted field is left alone, and `note: ""` clears the note.

    Moving the date moves the report period with it, so the two can never drift apart.
    """
    return await service.update_expense(expense_id, payload)


@router.delete(
    "/{expenseId}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404),
    summary="Delete an expense",
)
async def delete_expense(service: ServiceDep, expense_id: ExpenseIdPath) -> Response:
    await service.delete_expense(expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
