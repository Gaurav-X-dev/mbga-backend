"""Head-office view of customer KYC, across every merchant.

The merchant channel already reviews its own queue (`kyc_router`); this is the same data
without the tenancy filter, so head office can see the whole network, spot a merchant whose
queue is backing up, and open any single application.

Read-only on purpose. Approving and rejecting stay with the merchant who knows the customer
and holds the relationship — head office looking over the whole network is a different job
from deciding one application, and giving both to one screen invites the wrong one.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.constants import ApplicationStatus, DocumentStatus, to_mobile_document_status
from app.modules.customers.mapping import CustomerViewLoader, application_response
from app.modules.customers.business_schemas import KycApplicationResponse
from app.modules.customers.models import CustomerProfile, KycApplication
from app.modules.merchants.models import Merchant
from app.shared.authorization.dependencies import require_permission
from app.shared.business.pagination import Page, page_params
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/kyc/applications", tags=["admin-customer-kyc"])

REVIEW = Depends(require_permission("customers.review"))
DOCUMENT_REVIEW = Depends(require_permission("customer_documents.review"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class AdminKycItem(BaseModel):
    id: str
    customer_id: str
    customer_name: str | None
    customer_mobile: str | None
    customer_type: str | None
    city: str | None
    merchant_id: str | None
    merchant_name: str | None
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None
    reviewed_by_name: str | None
    rejection_reason: str | None
    document_count: int
    verified_document_count: int


class AdminKycListResponse(BaseModel):
    items: list[AdminKycItem]
    total: int
    limit: int
    offset: int


class AdminKycStats(BaseModel):
    pending: int
    approved: int
    rejected: int
    total: int


@router.get(
    "",
    response_model=AdminKycListResponse,
    dependencies=[REVIEW],
    responses=error_responses(401, 403, 422),
    summary="List customer KYC applications across merchants",
)
async def list_applications(
    session: SessionDep,
    page: Annotated[Page, Depends(page_params)],
    status_filter: Annotated[
        str, Query(alias="status", description="PENDING (default), APPROVED, REJECTED or ALL.")
    ] = ApplicationStatus.PENDING.value,
    merchant_id: Annotated[str | None, Query(description="Only this merchant's applications.")] = None,
    search: Annotated[str | None, Query(description="Matches customer name or mobile number.")] = None,
) -> AdminKycListResponse:
    statement: Select = (
        select(KycApplication, CustomerProfile, Merchant)
        .join(CustomerProfile, CustomerProfile.id == KycApplication.customer_id)
        .join(Merchant, Merchant.id == KycApplication.merchant_id, isouter=True)
    )

    value = (status_filter or "").strip().upper()
    if value and value != "ALL":
        if value not in ApplicationStatus.__members__:
            raise ApiError(
                "VALIDATION_ERROR",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[
                    {"field": "status", "code": "invalid", "message": "Use PENDING, APPROVED, REJECTED or ALL."}
                ],
            )
        statement = statement.where(KycApplication.status == value)
    if merchant_id:
        statement = statement.where(KycApplication.merchant_id == merchant_id)
    if search:
        like = f"%{search.strip()}%"
        # `name` is the business name and `owner_name` the person; a reviewer may recall either.
        statement = statement.where(
            or_(
                CustomerProfile.name.ilike(like),
                CustomerProfile.owner_name.ilike(like),
                CustomerProfile.mobile_number.ilike(like),
            )
        )

    # Newest submission first, matching the merchant queue: the reviewer works the freshest.
    statement = statement.order_by(KycApplication.submitted_at.desc(), KycApplication.id)
    total = int(await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0)
    rows = (await session.execute(statement.limit(page.limit).offset(page.offset))).all()

    documents = await CustomerViewLoader(session).documents_for(
        [row.CustomerProfile.id for row in rows]
    )
    items = []
    for row in rows:
        customer_documents = documents.get(row.CustomerProfile.id, [])
        items.append(
            AdminKycItem(
                id=row.KycApplication.id,
                customer_id=row.CustomerProfile.id,
                customer_name=row.CustomerProfile.name or row.CustomerProfile.owner_name,
                customer_mobile=row.CustomerProfile.mobile_number,
                customer_type=row.CustomerProfile.customer_type,
                city=row.CustomerProfile.address_city,
                merchant_id=row.KycApplication.merchant_id,
                merchant_name=row.Merchant.business_name if row.Merchant else None,
                status=row.KycApplication.status,
                submitted_at=row.KycApplication.submitted_at,
                reviewed_at=row.KycApplication.reviewed_at,
                reviewed_by_name=row.KycApplication.reviewed_by_name,
                rejection_reason=row.KycApplication.rejection_reason,
                document_count=len(customer_documents),
                # A verified document is stored as "APPROVED"; the mobile/web vocabulary calls
                # it VERIFIED. Translating here rather than comparing the raw column keeps this
                # count from silently reading zero.
                verified_document_count=sum(
                    1
                    for document in customer_documents
                    if to_mobile_document_status(document.status) == DocumentStatus.VERIFIED.value
                ),
            )
        )
    return AdminKycListResponse(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/stats",
    response_model=AdminKycStats,
    dependencies=[REVIEW],
    responses=error_responses(401, 403),
    summary="KYC queue counts across merchants",
)
async def application_stats(session: SessionDep) -> AdminKycStats:
    rows = (
        await session.execute(select(KycApplication.status, func.count()).group_by(KycApplication.status))
    ).all()
    counts = {str(value).upper(): int(count or 0) for value, count in rows}
    return AdminKycStats(
        pending=counts.get("PENDING", 0),
        approved=counts.get("APPROVED", 0),
        rejected=counts.get("REJECTED", 0),
        total=sum(counts.values()),
    )


@router.get(
    "/{application_id}",
    response_model=KycApplicationResponse,
    dependencies=[REVIEW, DOCUMENT_REVIEW],
    responses=error_responses(401, 403, 404),
    summary="KYC application detail",
)
async def application_detail(application_id: str, session: SessionDep) -> KycApplicationResponse:
    """The same response the merchant reviewer sees, without the tenancy check.

    Requires `customer_documents.review` as well as `customers.review`, because the detail
    carries document metadata: an admin allowed to see the queue is not automatically
    allowed to see what customers uploaded.
    """
    loader = CustomerViewLoader(session)
    application = await session.scalar(select(KycApplication).where(KycApplication.id == application_id))
    if application is None:
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
