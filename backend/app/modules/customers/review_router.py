"""Merchant-scoped review of customer registrations (SRS FR-CM-05).

Reviewers use the Merchant channel and need `customers.view`, `customers.approve` or `customers.reject`.
Reviewers only see applications submitted with their own merchant code.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.account_state import (
    CUSTOMER_APPROVED,
    CUSTOMER_REJECTED,
    CUSTOMER_ROLE_CODE,
    CUSTOMER_UNDER_REVIEW,
    AccountStateResolver,
)
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import CustomerDocument, CustomerProfile
from app.modules.customers.schemas import (
    CustomerProfileResponse,
    CustomerRejectRequest,
    CustomerReviewListResponse,
)
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/customers", tags=["merchant-customers"])
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))


async def _merchant_id(session: AsyncSession, context: AuthContext) -> str:
    user = await session.get(User, context.user_id)
    state = await AccountStateResolver(session).resolve(user, LoginChannel.MERCHANT)
    if not state.allowed or not state.merchant:
        raise ApiError("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN)
    return state.merchant["id"]


async def _scoped_profile(session: AsyncSession, context: AuthContext, customer_id: str) -> CustomerProfile:
    merchant_id = await _merchant_id(session, context)
    profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.id == customer_id).with_for_update())
    # Applications of other merchants are reported as not found.
    if profile is None or profile.merchant_id != merchant_id:
        raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return profile


def _audit(session: AsyncSession, event_type: str, actor_user_id: str, profile: CustomerProfile, message: str) -> None:
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type=event_type,
            actor_user_id=actor_user_id,
            entity_type="customer_profile",
            entity_id=profile.id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )


@router.get(
    "",
    response_model=CustomerReviewListResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.view"))],
    responses=error_responses(401, 403),
)
async def list_customer_applications(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
    status_filter: Annotated[str, Query(alias="status")] = CUSTOMER_UNDER_REVIEW,
) -> CustomerReviewListResponse:
    merchant_id = await _merchant_id(session, context)
    result = await session.execute(
        select(CustomerProfile)
        .where(CustomerProfile.merchant_id == merchant_id, CustomerProfile.status == status_filter.upper())
        .order_by(CustomerProfile.submitted_at, CustomerProfile.created_at)
        .limit(200)
    )
    return CustomerReviewListResponse(items=[CustomerProfileResponse.model_validate(p, from_attributes=True) for p in result.scalars()])


@router.post(
    "/{customer_id}/approve",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.approve"))],
    responses=error_responses(401, 403, 404, 409),
)
async def approve_customer(
    customer_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> CustomerProfileResponse:
    profile = await _scoped_profile(session, context, customer_id)
    if profile.status != CUSTOMER_UNDER_REVIEW:
        raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT)
    pending_document = await session.scalar(
        select(CustomerDocument.id).where(
            CustomerDocument.customer_id == profile.id,
            CustomerDocument.is_mandatory.is_(True),
            CustomerDocument.status != "APPROVED",
        )
    )
    if pending_document is not None:
        raise ApiError("DOCUMENTS_PENDING_APPROVAL", status.HTTP_409_CONFLICT)
    user = await session.get(User, profile.user_id) if profile.user_id else None
    if user is None:
        raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT, "The applicant has not verified the mobile number.")
    now = datetime.now(UTC)
    profile.status = CUSTOMER_APPROVED
    profile.reviewed_by = context.user_id
    profile.reviewed_at = now
    profile.rejection_reason = None
    profile.updated_at = now
    if user.status == "PENDING":
        user.status = "ACTIVE"
        user.updated_at = now
    await _ensure_customer_role(session, user.id, profile.merchant_id, context.user_id, now)
    _audit(session, "customer.approved", context.user_id, profile, "Customer registration approved")
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


@router.post(
    "/{customer_id}/reject",
    response_model=CustomerProfileResponse,
    dependencies=[MERCHANT_ONLY, Depends(require_permission("customers.reject"))],
    responses=error_responses(401, 403, 404, 409, 422),
)
async def reject_customer(
    customer_id: str,
    payload: CustomerRejectRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> CustomerProfileResponse:
    profile = await _scoped_profile(session, context, customer_id)
    if profile.status != CUSTOMER_UNDER_REVIEW:
        raise ApiError("INVALID_STATUS_TRANSITION", status.HTTP_409_CONFLICT)
    now = datetime.now(UTC)
    profile.status = CUSTOMER_REJECTED
    profile.rejection_reason = payload.reason.strip()
    profile.reviewed_by = context.user_id
    profile.reviewed_at = now
    profile.updated_at = now
    _audit(session, "customer.rejected", context.user_id, profile, "Customer registration rejected")
    await session.commit()
    return CustomerProfileResponse.model_validate(profile, from_attributes=True)


async def _ensure_customer_role(session: AsyncSession, user_id: str, merchant_id: str, actor_user_id: str, now: datetime) -> None:
    role = await session.scalar(select(Role).where(Role.code == CUSTOMER_ROLE_CODE, Role.is_active.is_(True)))
    if role is None:
        raise ApiError("INTERNAL_ERROR", status.HTTP_500_INTERNAL_SERVER_ERROR, "The customer role is not configured.")
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.scope_type == "merchant",
            UserRole.scope_id == merchant_id,
        )
    )
    if existing is not None:
        existing.is_active = True
        existing.valid_until = None
        return
    session.add(
        UserRole(
            id=str(uuid4()),
            user_id=user_id,
            role_id=role.id,
            assigned_at=now,
            assigned_by=actor_user_id,
            valid_from=None,
            valid_until=None,
            is_active=True,
            scope_type="merchant",
            scope_id=merchant_id,
        )
    )
