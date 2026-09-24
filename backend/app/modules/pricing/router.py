"""Merchant pricing routes (spec endpoints 1-6).

Two routers, because the paths live in two places the app already knows:

* `pricing_router` - `/pricing/...`, the More -> Pricing -> Standard tab.
* `customer_pricing_router` - `/customers/{customerId}/pricing...`, the Customer Details ->
  Price Setting tab. Mounted beside the existing customer routes; the paths do not overlap
  with `/customers/{customer_id}` or `/customers/{customer_id}/eligibility`.

Reads need `pricing.view`, writes need `pricing.manage` - the permissions already seeded in
`roles/seeds.py`. No new permission is introduced by this slice, and no role's grants are
changed: `scripts/grant_pricing_permissions.py` grants them per deployment, the way customer
and KYC authority is granted.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.pricing.schemas import (
    CustomerPriceItem,
    CustomerPricingResponse,
    PricingChangeLogPage,
    PricingMonthResponse,
    SetCustomerPriceOverrideRequest,
    UpdatePriceEntryRequest,
)
from app.modules.pricing.service import ChangeLogFilters, PricingService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

pricing_router = APIRouter(prefix="/pricing", tags=["Merchant Pricing"])
customer_pricing_router = APIRouter(prefix="/customers", tags=["Merchant Pricing"])

MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
CAN_VIEW = Depends(require_permission("pricing.view"))
CAN_MANAGE = Depends(require_permission("pricing.manage"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

CylinderTypePath = Annotated[
    str,
    Path(
        alias="cylinderType",
        max_length=40,
        description="LPG_5KG, LPG_19KG, LPG_47_5KG_L, LPG_47_5KG_V or LPG_422KG_HIPPO.",
    ),
]


def _service(session: SessionDep, actor: ActorDep) -> PricingService:
    return PricingService(session, actor)


ServiceDep = Annotated[PricingService, Depends(_service)]


# --- 1. Pricing months ------------------------------------------------------------------------


@pricing_router.get(
    "/months",
    response_model=list[PricingMonthResponse],
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403),
    summary="Pricing months",
)
async def list_pricing_months(service: ServiceDep) -> list[PricingMonthResponse]:
    """Every pricing month for this merchant, newest first, STANDARD entries only.

    The current month is opened on first read if it does not exist yet, carrying the
    previous month's rates forward, so the Standard tab is never empty.
    """
    return await service.months()


# --- 2. Mid-month price change -----------------------------------------------------------------


@pricing_router.put(
    "/months/{pricingMonthId}/entries",
    response_model=PricingMonthResponse,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Change a price (mid-month)",
)
async def update_pricing_entry(
    payload: UpdatePriceEntryRequest,
    service: ServiceDep,
    pricing_month_id: Annotated[str, Path(alias="pricingMonthId", max_length=120)],
) -> PricingMonthResponse:
    """Update one cylinder type's rate inside a month, at any point during that month.

    The entry is updated, an immutable `pricing_change_logs` row records the old and new
    values with the acting user, and the month's `updatedBy`/`updatedAt` move - all in one
    transaction. `customerPrice` is computed by the database and is never taken from the
    request body.
    """
    return await service.update_entry(pricing_month_id, payload)


# --- 3. Change logs -----------------------------------------------------------------------------


@pricing_router.get(
    "/change-logs",
    response_model=PricingChangeLogPage,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 422),
    summary="Price change history",
)
async def list_pricing_change_logs(
    service: ServiceDep,
    cylinder_type: Annotated[str | None, Query(alias="cylinderType")] = None,
    tier: Annotated[str | None, Query()] = None,
    pricing_month_id: Annotated[str | None, Query(alias="pricingMonthId", max_length=120)] = None,
    date_from: Annotated[date | None, Query(alias="from", description="Earliest effectiveFrom.")] = None,
    date_to: Annotated[date | None, Query(alias="to", description="Latest effectiveFrom.")] = None,
    page: Annotated[int, Query(ge=1, description="1-based page number.")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE, description="Alias for pageSize.")] = None,
    offset: Annotated[int | None, Query(ge=0, description="Rows to skip, instead of page.")] = None,
) -> PricingChangeLogPage:
    """Newest first. No screen reads this yet; it is the data a price-history screen needs.

    Paged as this endpoint's own contract documents (`page`/`pageSize`), and also accepting
    the `limit`/`offset` the rest of the API uses. The response carries all four keys, so
    either caller reads what it expects.
    """
    return await service.change_logs(
        ChangeLogFilters(
            cylinder_type=cylinder_type,
            tier=tier,
            pricing_month_id=pricing_month_id,
            date_from=date_from,
            date_to=date_to,
        ),
        page=page,
        page_size=limit or page_size,
        offset=offset,
    )


# --- 4-6. Per-customer price overrides -----------------------------------------------------------


@customer_pricing_router.get(
    "/{customer_id}/pricing",
    response_model=CustomerPricingResponse,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 404),
    summary="Customer pricing",
)
async def customer_pricing(customer_id: str, service: ServiceDep) -> CustomerPricingResponse:
    """One row per cylinder type this customer may order - Hippo is industrial-only.

    `effectivePrice` is the override where one is set, the tier price otherwise.
    """
    return await service.customer_pricing(customer_id)


@customer_pricing_router.put(
    "/{customer_id}/pricing/{cylinderType}",
    response_model=CustomerPriceItem,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404, 422),
    summary="Set a customer price",
)
async def set_customer_price_override(
    payload: SetCustomerPriceOverrideRequest,
    service: ServiceDep,
    customer_id: str,
    cylinder_type: CylinderTypePath,
) -> CustomerPriceItem:
    """Set or change this customer's own price for one cylinder type.

    An upsert - calling it again just moves the price. It takes effect everywhere the
    customer is priced, not only on this screen, because quoting, order creation and the
    customer's pricing view all resolve through `resolve_customer_price`.
    """
    return await service.set_override(customer_id, cylinder_type, payload)


@customer_pricing_router.delete(
    "/{customer_id}/pricing/{cylinderType}",
    response_model=CustomerPriceItem,
    status_code=status.HTTP_200_OK,
    dependencies=[MERCHANT_ONLY, CAN_MANAGE],
    responses=error_responses(401, 403, 404),
    summary="Remove a customer price",
)
async def remove_customer_price_override(
    service: ServiceDep,
    customer_id: str,
    cylinder_type: CylinderTypePath,
) -> CustomerPriceItem:
    """Remove the override; the customer reverts to the standard tier price.

    Recorded as a `REMOVE` row in `customer_price_override_logs` rather than a deletion
    that leaves no trace.
    """
    return await service.remove_override(customer_id, cylinder_type)
