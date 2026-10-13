"""Tenant-scoped credit controls for authorised merchant staff."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService
from app.modules.authentication.constants import LoginChannel
from app.modules.credit.models import CreditSettingsAudit
from app.modules.credit.schemas import CustomerCreditUpdate
from app.modules.credit.service import CreditLimitService
from app.modules.customers.dependencies import ActorDep
from app.modules.customers.models import CustomerProfile
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/credit", tags=["Merchant Credit Control"])
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
MANAGE = Depends(require_permission("credit.manage"))


@router.patch(
    "/customers/{customer_id}",
    dependencies=[MERCHANT_ONLY, MANAGE],
    responses=error_responses(401, 403, 404, 422),
    summary="Update credit terms for this merchant's customer",
)
async def update_customer_credit(
    customer_id: str,
    payload: CustomerCreditUpdate,
    session: SessionDep,
    actor: ActorDep,
):
    """Change credit terms without allowing cross-merchant customer-id probing."""
    merchant_id = actor.require_merchant_id()
    customer = await session.scalar(
        select(CustomerProfile)
        .where(
            CustomerProfile.id == customer_id,
            CustomerProfile.merchant_id == merchant_id,
        )
        .with_for_update()
    )
    if customer is None:
        raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)

    now = datetime.now(UTC)
    reason = payload.reason.strip()
    session.add(
        CreditSettingsAudit(
            id=str(uuid4()),
            customer_id=customer.id,
            merchant_id=merchant_id,
            old_enabled=customer.credit_enabled,
            new_enabled=payload.credit_enabled,
            old_limit=customer.credit_limit,
            new_limit=payload.credit_limit,
            old_days=customer.credit_days,
            new_days=payload.credit_days,
            changed_by_user_id=actor.user_id,
            changed_by_name=actor.display_name,
            reason=reason,
            created_at=now,
        )
    )
    customer.credit_enabled = payload.credit_enabled
    customer.credit_limit = payload.credit_limit
    customer.credit_days = payload.credit_days
    customer.updated_at = now
    await AuditLogService(session).write_event(
        AuditLogCreate(
            event_type="CUSTOMER_CREDIT_CHANGED",
            actor_user_id=actor.user_id,
            entity_type="customer",
            entity_id=customer.id,
            message=f"Merchant changed customer credit terms. Reason: {reason}",
            login_channel=LoginChannel.MERCHANT.value,
            result="SUCCESS",
        )
    )
    await session.commit()

    snapshot = await CreditLimitService(session).snapshot(
        customer.id, include_disabled_usage=True
    )
    return {
        "customerId": customer.id,
        "creditEnabled": customer.credit_enabled,
        "creditLimit": customer.credit_limit,
        "creditDays": customer.credit_days,
        "usedCredit": snapshot.used,
        "availableCredit": snapshot.available,
    }

