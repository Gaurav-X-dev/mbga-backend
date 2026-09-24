"""Merchant customer management: create, list, detail, eligibility (spec §7).

Every query in this module is scoped to the actor's merchant before it runs, and a row
belonging to another merchant is reported as **404** rather than 403, so customer ids cannot
be probed across tenants.

Permission names are the ones already seeded in `roles/seeds.py` — `customers.create`,
`customers.view`, `orders.create`. No new permission is introduced by this slice.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers import eligibility as eligibility_policy
from app.modules.customers.business_schemas import (
    CustomerListResponse,
    CustomerRegistrationRequest,
    CustomerResponse,
    EligibilityResponse,
)
from app.modules.customers.constants import MOBILE_TO_ACCOUNT_STATUSES, CustomerType
from app.modules.customers.dependencies import ActorDep, RegistrationDep
from app.modules.customers.mapping import CustomerViewLoader
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.merchants.models import Merchant
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.actor import BusinessActor
from app.shared.business.pagination import Page, page_params, paginate
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/customers", tags=["Merchant Customers"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


async def _merchant_of(session: AsyncSession, actor: BusinessActor) -> Merchant:
    merchant = await session.get(Merchant, actor.require_merchant_id())
    if merchant is None:
        raise ApiError("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN)
    return merchant


async def _owned_profile(session: AsyncSession, actor: BusinessActor, customer_id: str) -> CustomerProfile:
    profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.id == customer_id))
    if profile is None or profile.merchant_id != actor.require_merchant_id():
        raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return profile


@router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.create"))],
    responses=error_responses(401, 403, 409, 422),
    summary="Add a customer",
)
async def create_customer(
    payload: CustomerRegistrationRequest,
    actor: ActorDep,
    service: RegistrationDep,
    session: SessionDep,
) -> CustomerResponse:
    """Create a customer, its login identity, documents, sites and pending application.

    The merchant and the creating staff member both come from the session. The body cannot
    set merchant id, customer code, pricing tier, status or any review field.
    """
    merchant = await _merchant_of(session, actor)
    profile, _application = await service.create_customer_by_merchant(payload, actor, merchant)
    # One commit for the whole operation, so a failure anywhere above leaves no user,
    # profile, document link, site or application behind.
    await session.commit()
    await session.refresh(profile)
    return await CustomerViewLoader(session).customer_view(profile)


@router.get(
    "",
    response_model=CustomerListResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.view"))],
    responses=error_responses(401, 403),
    summary="List customers",
)
async def list_customers(
    actor: ActorDep,
    session: SessionDep,
    page: Annotated[Page, Depends(page_params)],
    search: Annotated[str | None, Query(max_length=120, description="Business name, owner name, mobile or code.")] = None,
    customer_type: Annotated[str | None, Query(alias="customerType", description="RETAIL, INDUSTRIAL or ALL.")] = None,
    account_status: Annotated[str | None, Query(alias="accountStatus", description="A CustomerAccountStatus or ALL.")] = None,
) -> CustomerListResponse:
    statement = select(CustomerProfile).where(CustomerProfile.merchant_id == actor.require_merchant_id())
    statement = _apply_filters(statement, search=search, customer_type=customer_type, account_status=account_status)
    # Spec §7.2: business name A→Z. Rows without a name yet sort last rather than first.
    statement = statement.order_by(func.coalesce(CustomerProfile.name, "~"), CustomerProfile.created_at)
    profiles, total = await paginate(session, statement, page)
    items = await CustomerViewLoader(session).customer_views(list(profiles))
    return CustomerListResponse(items=items, total=total, limit=page.limit, offset=page.offset)


def _apply_filters(statement, *, search: str | None, customer_type: str | None, account_status: str | None):
    """Translate the app's query words into backend statuses before filtering.

    `accountStatus=PENDING` means the mobile app's PENDING, which is the backend's
    UNDER_REVIEW - so the mapping has to happen here and not be left to the caller.
    """
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                CustomerProfile.name.ilike(term),
                CustomerProfile.owner_name.ilike(term),
                CustomerProfile.mobile_number.ilike(term),
                CustomerProfile.code.ilike(term),
            )
        )
    if customer_type and customer_type.upper() not in {"ALL", ""}:
        value = customer_type.upper()
        if value not in CustomerType.__members__:
            raise _invalid_filter("customerType", "Use RETAIL, INDUSTRIAL or ALL.")
        statement = statement.where(CustomerProfile.customer_type == value)
    if account_status and account_status.upper() not in {"ALL", ""}:
        value = account_status.upper()
        backend_statuses = MOBILE_TO_ACCOUNT_STATUSES.get(value)
        if backend_statuses is None:
            raise _invalid_filter("accountStatus", "Use NEW, PENDING, APPROVED, REJECTED, SUSPENDED or ALL.")
        statement = statement.where(CustomerProfile.status.in_(backend_statuses))
    return statement


def _invalid_filter(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_ERROR",
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        fields=[{"field": field, "code": "invalid", "message": message}],
    )


@router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.view"))],
    responses=error_responses(401, 403, 404),
    summary="Customer detail",
)
async def customer_detail(customer_id: str, actor: ActorDep, session: SessionDep) -> CustomerResponse:
    profile = await _owned_profile(session, actor, customer_id)
    return await CustomerViewLoader(session).customer_view(profile)


@router.get(
    "/{customer_id}/eligibility",
    response_model=EligibilityResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("orders.create"))],
    responses=error_responses(401, 403, 404),
    summary="Order eligibility",
)
async def customer_eligibility(customer_id: str, actor: ActorDep, session: SessionDep) -> EligibilityResponse:
    """Whether an order may be placed for this customer, and why not.

    The same policy object will be called by order creation, so the Create Order screen and
    the backend can never disagree about who may order.
    """
    profile = await _owned_profile(session, actor, customer_id)
    sites = list(
        await session.scalars(select(CustomerDeliverySite).where(CustomerDeliverySite.customer_id == profile.id))
    )
    outcome = eligibility_policy.evaluate(profile, sites)
    return EligibilityResponse(eligible=outcome.eligible, reasons=outcome.reasons)
