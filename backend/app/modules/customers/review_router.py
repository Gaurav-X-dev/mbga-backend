"""Merchant-scoped approval and rejection of customer registrations (SRS FR-CM-05).

The two routes keep the paths, the permissions and the response shape they already had - the
merchant app and the web panel are integrated against them. What changed is the logic behind
them, which now lives in `KycReviewService`: the KYC application row is decided alongside the
profile, approval verifies the documents and sites rather than only the status, and both
decisions take a row lock so two concurrent reviewers cannot both win.

Listing customers moved to `merchant_router.py`, which serves the same `GET /customers` path
with the filters and pagination the mobile contract asks for. Its response still has `items`
with an `id` per row, so existing callers keep working.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, ReviewDep
from app.modules.customers.schemas import CustomerProfileResponse, CustomerRejectRequest
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/customers", tags=["merchant-customers"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "/{customer_id}/approve",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.approve"))],
    responses=error_responses(401, 403, 404, 409),
    summary="Approve a customer registration",
)
async def approve_customer(
    customer_id: str,
    actor: ActorDep,
    service: ReviewDep,
    session: SessionDep,
) -> CustomerProfileResponse:
    """Approve the customer's pending application.

    A second approval returns `409 INVALID_STATUS_TRANSITION`, and so does an approval racing
    a rejection - the row lock means exactly one of the two decisions is recorded.
    """
    profile = await service.locked_profile(customer_id, actor)
    await service.approve(profile, actor)
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


@router.post(
    "/{customer_id}/reject",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.reject"))],
    responses=error_responses(401, 403, 404, 409, 422),
    summary="Reject a customer registration",
)
async def reject_customer(
    customer_id: str,
    payload: CustomerRejectRequest,
    actor: ActorDep,
    service: ReviewDep,
    session: SessionDep,
) -> CustomerProfileResponse:
    profile = await service.locked_profile(customer_id, actor)
    await service.reject(profile, actor, payload.reason)
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)
