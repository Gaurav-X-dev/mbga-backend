"""Merchant KYC review: list and application detail (spec §8.1, §8.2).

Kept as its own resource rather than folded into the customer list, because the mobile app
calls `customerService.listKycApplications` and `customerService.getKycApplication` against
these paths and renders a `KycApplication`, not a `Customer`. The *queries* are shared with
the customer routes through `CustomerViewLoader`; only the response shape differs.

The approve and reject routes are unchanged in path and shape and stay in `review_router.py`.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.business_schemas import (
    KycApplicationListResponse,
    KycApplicationResponse,
    RevealedDocumentNumber,
)
from app.modules.customers.constants import ApplicationStatus
from app.modules.customers.dependencies import ActorDep, get_document_cipher
from app.modules.customers.mapping import CustomerViewLoader, application_response
from app.modules.audit_logs.models import AuditLog
from app.modules.customers.models import CustomerDocument, CustomerProfile, KycApplication
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.pagination import Page, page_params, paginate
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses
from app.shared.crypto.field_cipher import FieldCipher

router = APIRouter(prefix="/kyc/applications", tags=["Merchant KYC Review"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
# B4: the seeded permission names are used as they are; no renaming in this slice.
REVIEW = Depends(require_permission("customers.review"))
DOCUMENT_REVIEW = Depends(require_permission("customer_documents.review"))
#: On top of the review rights, because this is the one route that returns an identifier in
#: full. A reviewer who may read the queue does not automatically get to read Aadhaar numbers.
VERIFY = Depends(require_permission("customers.verify"))
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


@router.get(
    "/{application_id}/documents/{document_id}/number",
    response_model=RevealedDocumentNumber,
    dependencies=[MERCHANT_ONLY, REVIEW, DOCUMENT_REVIEW, VERIFY],
    responses=error_responses(401, 403, 404, 409),
    summary="Reveal one document's full number, for verification",
)
async def reveal_document_number(
    application_id: str,
    document_id: str,
    actor: ActorDep,
    session: SessionDep,
    cipher: Annotated[FieldCipher, Depends(get_document_cipher)],
) -> RevealedDocumentNumber:
    """The number as the customer typed it, for checking against the scan.

    Everywhere else in this project a document number is masked - `mapping.py` is written so
    that an unmasked identifier cannot leave through a list or a detail screen. That is the
    right default for an Aadhaar or a PAN, and it stays.

    But a reviewer is asked to decide whether the number on the form matches the photograph of
    the card, and `XXXXXXXX9012` cannot be compared with anything. So there is exactly one way
    to see the whole value: this route, one document at a time, behind `customers.verify` on
    top of the review permissions - and **every call is written to the audit log**, with who
    asked and which document they opened. Nobody reads an identifier here without leaving their
    name on it.

    `409` when the document carries no stored number - an older row, or one whose upload never
    finished.
    """
    merchant_id = actor.require_merchant_id()
    application = await session.scalar(select(KycApplication).where(KycApplication.id == application_id))
    if application is None or application.merchant_id != merchant_id:
        raise ApiError("APPLICATION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    document = await session.scalar(
        select(CustomerDocument).where(
            CustomerDocument.id == document_id,
            CustomerDocument.customer_id == application.customer_id,
        )
    )
    if document is None:
        # A document belonging to somebody else reads the same as one that is not there.
        raise ApiError("DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if not document.number_encrypted:
        raise ApiError(
            "DOCUMENT_NUMBER_UNAVAILABLE",
            status.HTTP_409_CONFLICT,
            "This document has no stored number to show.",
        )

    number = cipher.decrypt(document.number_encrypted)
    # Written before the value is returned, and committed with it: a read that was not recorded
    # is a read nobody can answer for later.
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="customer_document.number_revealed",
            actor_user_id=actor.user_id,
            entity_type="customer_document",
            entity_id=document.id,
            message=f"{document.document_type} number shown for application {application_id}",
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return RevealedDocumentNumber(
        document_id=document.id,
        document_type=document.document_type,
        number=number,
        number_masked=document.number_masked or "",
    )


async def _profiles_for(session: AsyncSession, customer_ids: list[str]) -> dict[str, CustomerProfile]:
    if not customer_ids:
        return {}
    rows = await session.scalars(select(CustomerProfile).where(CustomerProfile.id.in_(customer_ids)))
    return {profile.id: profile for profile in rows}
