"""Merchant V2 KYC queue, detail and application decisions."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, ReviewDep
from app.modules.customers.merchant_v2_schemas import (
    MerchantKycApplicationListResponseV2,
    MerchantKycApplicationResponseV2,
)
from app.modules.customers.merchant_v2_service import MerchantKycV2Service
from app.modules.customers.models import CustomerProfile, KycApplication
from app.modules.customers.schemas import CustomerProfileResponse, CustomerRejectRequest
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.pagination import Page, page_params, paginate
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/kyc/applications", tags=["Merchant V2 KYC Review"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
REVIEW = Depends(require_permission("customers.review"))
DOCUMENT_REVIEW = Depends(require_permission("customer_documents.review"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_merchant_kyc_v2_service(session: SessionDep) -> MerchantKycV2Service:
    return MerchantKycV2Service(session)


ServiceDep = Annotated[MerchantKycV2Service, Depends(get_merchant_kyc_v2_service)]


async def _profiles_for(
    session: AsyncSession, customer_ids: list[str]
) -> dict[str, CustomerProfile]:
    if not customer_ids:
        return {}
    rows = await session.scalars(select(CustomerProfile).where(CustomerProfile.id.in_(customer_ids)))
    return {profile.id: profile for profile in rows}


@router.get(
    "",
    response_model=MerchantKycApplicationListResponseV2,
    dependencies=[MERCHANT_ONLY, REVIEW, DOCUMENT_REVIEW],
    responses=error_responses(401, 403, 422),
)
async def list_applications_v2(
    actor: ActorDep,
    session: SessionDep,
    service: ServiceDep,
    page: Annotated[Page, Depends(page_params)],
    status_filter: Annotated[str, Query(alias="status")] = "PENDING",
) -> MerchantKycApplicationListResponseV2:
    statement = select(KycApplication).where(
        KycApplication.merchant_id == actor.require_merchant_id()
    )
    value = (status_filter or "").strip().upper()
    if value and value != "ALL":
        if value not in {"PENDING", "APPROVED", "REJECTED"}:
            raise ApiError(
                "VALIDATION_ERROR",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                fields=[
                    {
                        "field": "status",
                        "code": "invalid",
                        "message": "Use PENDING, APPROVED, REJECTED or ALL.",
                    }
                ],
            )
        statement = statement.where(KycApplication.status == value)
    statement = statement.order_by(KycApplication.submitted_at.desc(), KycApplication.id)
    applications, total = await paginate(session, statement, page)
    applications = list(applications)
    profiles = await _profiles_for(session, [item.customer_id for item in applications])
    return MerchantKycApplicationListResponseV2(
        items=await service.applications(applications, profiles),
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{application_id}",
    response_model=MerchantKycApplicationResponseV2,
    dependencies=[MERCHANT_ONLY, REVIEW, DOCUMENT_REVIEW],
    responses=error_responses(401, 403, 404),
)
async def application_detail_v2(
    application_id: str,
    actor: ActorDep,
    session: SessionDep,
    service: ServiceDep,
) -> MerchantKycApplicationResponseV2:
    application = await session.scalar(
        select(KycApplication).where(KycApplication.id == application_id)
    )
    if application is None or application.merchant_id != actor.require_merchant_id():
        raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    profile = await session.get(CustomerProfile, application.customer_id)
    if profile is None:
        raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return await service.application(application, profile)


@router.post(
    "/{application_id}/approve",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.approve"))],
    responses=error_responses(401, 403, 404, 409),
)
async def approve_application_v2(
    application_id: str,
    actor: ActorDep,
    review: ReviewDep,
    service: ServiceDep,
    session: SessionDep,
) -> CustomerProfileResponse:
    profile = await service.approve(application_id, actor, review)
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


@router.post(
    "/{application_id}/reject",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.reject"))],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def reject_application_v2(
    application_id: str,
    payload: CustomerRejectRequest,
    actor: ActorDep,
    review: ReviewDep,
    service: ServiceDep,
    session: SessionDep,
) -> CustomerProfileResponse:
    profile = await service.reject(application_id, actor, review, payload.reason)
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)
