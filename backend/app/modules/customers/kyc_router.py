"""Merchant KYC review: list and application detail (spec §8.1, §8.2).

Kept as its own resource rather than folded into the customer list, because the mobile app
calls `customerService.listKycApplications` and `customerService.getKycApplication` against
these paths and renders a `KycApplication`, not a `Customer`. The *queries* are shared with
the customer routes through `CustomerViewLoader`; only the response shape differs.

The approve and reject routes are unchanged in path and shape and stay in `review_router.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.business_schemas import (
    KycApplicationListResponse,
    KycApplicationResponse,
)
from app.modules.customers.constants import ApplicationStatus
from app.modules.customers.dependencies import ActorDep
from app.modules.customers.mapping import CustomerViewLoader, application_response
from app.modules.customers.models import CustomerProfile, KycApplication
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.pagination import Page, page_params, paginate
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/kyc/applications", tags=["Merchant KYC Review"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
# B4: the seeded permission names are used as they are; no renaming in this slice.
REVIEW = Depends(require_permission("customers.review"))
DOCUMENT_REVIEW = Depends(require_permission("customer_documents.review"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get(
    "",
    response_model=KycApplicationListResponse,
    dependencies=[MERCHANT_ONLY, REVIEW],
    responses=error_responses(401, 403, 422),
    summary="List KYC applications",
)
async def list_applications(
    actor: ActorDep,
    session: SessionDep,
    page: Annotated[Page, Depends(page_params)],
    status_filter: Annotated[str, Query(alias="status", description="PENDING (default), APPROVED, REJECTED or ALL.")] = ApplicationStatus.PENDING.value,
) -> KycApplicationListResponse:
    statement = select(KycApplication).where(KycApplication.merchant_id == actor.require_merchant_id())
    value = (status_filter or "").strip().upper()
    if value and value != "ALL":
        if value not in ApplicationStatus.__members__:
            raise ApiError(
                "VALIDATION_ERROR",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[{"field": "status", "code": "invalid", "message": "Use PENDING, APPROVED, REJECTED or ALL."}],
            )
        statement = statement.where(KycApplication.status == value)
    # Spec §8.1: newest submission first, so the reviewer works the freshest queue.
    statement = statement.order_by(KycApplication.submitted_at.desc(), KycApplication.id)
    applications, total = await paginate(session, statement, page)
    applications = list(applications)
    profiles = await _profiles_for(session, [application.customer_id for application in applications])
    items = await CustomerViewLoader(session).application_views(applications, profiles)
    return KycApplicationListResponse(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/{application_id}",
    response_model=KycApplicationResponse,
    dependencies=[MERCHANT_ONLY, REVIEW, DOCUMENT_REVIEW],
    responses=error_responses(401, 403, 404),
    summary="KYC application detail",
)
async def application_detail(application_id: str, actor: ActorDep, session: SessionDep) -> KycApplicationResponse:
    """Load one application by its own id.

    Addressed by application id, not customer id, because a customer who was rejected and
    resubmitted has more than one — and the review screen opens the specific one the
    reviewer picked from the list.

    Document metadata is included here, which is why this route also requires
    `customer_documents.review`: a reviewer without it can see the queue but not the
    documents. Opening a document file itself goes through `/merchant/documents/{id}/url`.
    """
    loader = CustomerViewLoader(session)
    application = await session.scalar(select(KycApplication).where(KycApplication.id == application_id))
    if application is None or application.merchant_id != actor.require_merchant_id():
        # A foreign application is indistinguishable from one that does not exist.
        raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    profile = await session.get(CustomerProfile, application.customer_id)
    if profile is None:
        raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    sites = await loader.sites_for([profile.id])
    documents = await loader.documents_for([profile.id])
    return application_response(
        application,
        profile,
        sites=sites.get(profile.id, []),
        documents=documents.get(profile.id, []),
    )


async def _profiles_for(session: AsyncSession, customer_ids: list[str]) -> dict[str, CustomerProfile]:
    if not customer_ids:
        return {}
    rows = await session.scalars(select(CustomerProfile).where(CustomerProfile.id.in_(customer_ids)))
    return {profile.id: profile for profile in rows}
