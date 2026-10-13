"""Super-admin credit controls, reports and audit history."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService
from app.modules.authentication.constants import LoginChannel
from app.modules.credit.models import CreditOverrideAudit, CreditSettingsAudit
from app.modules.credit.schemas import CustomerCreditUpdate
from app.modules.credit.service import CreditLimitService
from app.modules.customers.dependencies import ActorDep
from app.modules.customers.models import CustomerProfile
from app.modules.platform_settings import service as platform_settings
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.notifications.models import NotificationOutbox

router = APIRouter(prefix="/credit", tags=["Admin Credit Control"])
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ADMIN = Depends(require_login_channel(LoginChannel.ADMIN))
VIEW = Depends(require_permission("credit.view"))
MANAGE = Depends(require_permission("credit.manage"))
OVERRIDE = Depends(require_permission("credit.override"))
_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class CreditSettingsUpdate(BaseModel):
    credit_limit_enabled: bool | None = Field(default=None, alias="creditLimitEnabled")
    reminders_enabled: bool | None = Field(default=None, alias="remindersEnabled")
    interval_hours: int | None = Field(default=None, alias="intervalHours", ge=1, le=2160)
    max_count: int | None = Field(default=None, alias="maxCount", ge=1, le=100)
    quiet_start_hour: int | None = Field(default=None, alias="quietStartHour", ge=0, le=23)
    quiet_end_hour: int | None = Field(default=None, alias="quietEndHour", ge=0, le=23)
    threshold_percent: int | None = Field(default=None, alias="thresholdPercent", ge=1, le=1000)
    block_push_cooldown_minutes: int | None = Field(
        default=None, alias="blockPushCooldownMinutes", ge=1, le=10080
    )
    message_template: str | None = Field(
        default=None, alias="messageTemplate", min_length=10, max_length=1000
    )
    model_config = _CAMEL


class OverrideRequest(BaseModel):
    amount: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)
    valid_for_minutes: int = Field(default=30, alias="validForMinutes", ge=1, le=1440)
    model_config = _CAMEL


def _settings(row):
    return {
        "creditLimitEnabled": row.credit_limit_enabled,
        "remindersEnabled": row.credit_reminders_enabled,
        "intervalHours": row.credit_reminder_interval_hours,
        "maxCount": row.credit_reminder_max_count,
        "quietStartHour": row.credit_quiet_start_hour,
        "quietEndHour": row.credit_quiet_end_hour,
        "thresholdPercent": row.credit_reminder_threshold_percent,
        "blockPushCooldownMinutes": row.credit_block_push_cooldown_minutes,
        "messageTemplate": row.credit_reminder_template,
    }


@router.get("/settings", dependencies=[ADMIN, VIEW])
async def read_credit_settings(session: SessionDep):
    return _settings(await platform_settings.load(session))


@router.patch("/settings", dependencies=[ADMIN, MANAGE])
async def update_credit_settings(
    payload: CreditSettingsUpdate, session: SessionDep, actor: ActorDep
):
    row = await platform_settings.load(session)
    values = payload.model_dump(exclude_none=True)
    mapping = {
        "credit_limit_enabled": "credit_limit_enabled",
        "reminders_enabled": "credit_reminders_enabled",
        "interval_hours": "credit_reminder_interval_hours",
        "max_count": "credit_reminder_max_count",
        "quiet_start_hour": "credit_quiet_start_hour",
        "quiet_end_hour": "credit_quiet_end_hour",
        "threshold_percent": "credit_reminder_threshold_percent",
        "block_push_cooldown_minutes": "credit_block_push_cooldown_minutes",
        "message_template": "credit_reminder_template",
    }
    changed: list[str] = []
    for key, value in values.items():
        attribute = mapping[key]
        if getattr(row, attribute) != value:
            changed.append(key)
            setattr(row, attribute, value)
    row.updated_by_user_id, row.updated_by_name, row.updated_at = (
        actor.user_id,
        actor.display_name,
        datetime.now(UTC),
    )
    if changed:
        await AuditLogService(session).write_event(
            AuditLogCreate(
                event_type="CREDIT_SETTINGS_CHANGED",
                actor_user_id=actor.user_id,
                entity_type="platform_settings",
                entity_id=row.id,
                message="Changed credit settings: " + ", ".join(changed),
                login_channel=LoginChannel.ADMIN.value,
                result="SUCCESS",
            )
        )
    await session.commit()
    return _settings(row)


@router.patch("/customers/{customer_id}", dependencies=[ADMIN, MANAGE])
async def update_customer_credit(
    customer_id: str, payload: CustomerCreditUpdate, session: SessionDep, actor: ActorDep
):
    customer = await session.scalar(
        select(CustomerProfile).where(CustomerProfile.id == customer_id).with_for_update()
    )
    if customer is None:
        raise ApiError("CUSTOMER_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    now = datetime.now(UTC)
    session.add(
        CreditSettingsAudit(
            id=str(uuid4()),
            customer_id=customer.id,
            merchant_id=customer.merchant_id,
            old_enabled=customer.credit_enabled,
            new_enabled=payload.credit_enabled,
            old_limit=customer.credit_limit,
            new_limit=payload.credit_limit,
            old_days=customer.credit_days,
            new_days=payload.credit_days,
            changed_by_user_id=actor.user_id,
            changed_by_name=actor.display_name,
            reason=payload.reason.strip(),
            created_at=now,
        )
    )
    customer.credit_enabled, customer.credit_limit, customer.credit_days = (
        payload.credit_enabled,
        payload.credit_limit,
        payload.credit_days,
    )
    customer.updated_at = now
    await session.commit()
    snapshot = await CreditLimitService(session).snapshot(customer.id, include_disabled_usage=True)
    return {
        "customerId": customer.id,
        "creditEnabled": customer.credit_enabled,
        "creditLimit": customer.credit_limit,
        "creditDays": customer.credit_days,
        "usedCredit": snapshot.used,
        "availableCredit": snapshot.available,
    }


@router.post("/customers/{customer_id}/overrides", status_code=201, dependencies=[ADMIN, OVERRIDE])
async def approve_override(
    customer_id: str, payload: OverrideRequest, session: SessionDep, actor: ActorDep
):
    snapshot = await CreditLimitService(session).snapshot(
        customer_id,
        proposed_amount=payload.amount,
        lock=True,
        include_disabled_usage=True,
    )
    now = datetime.now(UTC)
    row = CreditOverrideAudit(
        id=str(uuid4()),
        customer_id=customer_id,
        merchant_id=(await session.get(CustomerProfile, customer_id)).merchant_id,
        order_id=None,
        amount=payload.amount,
        used_credit=snapshot.used,
        credit_limit=snapshot.limit,
        reason=payload.reason.strip(),
        approved_by_user_id=actor.user_id,
        approved_by_name=actor.display_name,
        expires_at=now + timedelta(minutes=payload.valid_for_minutes),
        consumed_at=None,
        created_at=now,
    )
    session.add(row)
    await session.commit()
    return {
        "id": row.id,
        "customerId": customer_id,
        "amount": row.amount,
        "expiresAt": row.expires_at,
    }


@router.get("/customers", dependencies=[ADMIN, VIEW])
async def credit_report(
    session: SessionDep,
    merchant_id: Annotated[str | None, Query(alias="merchantId")] = None,
    exceeded_only: Annotated[bool, Query(alias="exceededOnly")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    query = (
        select(CustomerProfile)
        .order_by(CustomerProfile.name, CustomerProfile.id)
    )
    if merchant_id:
        query = query.where(CustomerProfile.merchant_id == merchant_id)
    customers = list(await session.scalars(query.limit(limit).offset(offset)))
    items = []
    for customer in customers:
        snapshot = await CreditLimitService(session).snapshot(
            customer.id, include_disabled_usage=True
        )
        if exceeded_only and snapshot.used <= snapshot.limit:
            continue
        items.append(
            {
                "customerId": customer.id,
                "customerName": customer.name or customer.owner_name,
                "merchantId": customer.merchant_id,
                "creditEnabled": customer.credit_enabled,
                "creditLimit": snapshot.limit,
                "creditDays": customer.credit_days,
                "usedCredit": snapshot.used,
                "availableCredit": snapshot.available,
                "exceeded": snapshot.used > snapshot.limit,
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/customers/{customer_id}/history", dependencies=[ADMIN, VIEW])
async def credit_history(customer_id: str, session: SessionDep):
    audits = list(
        await session.scalars(
            select(CreditSettingsAudit)
            .where(CreditSettingsAudit.customer_id == customer_id)
            .order_by(CreditSettingsAudit.created_at.desc())
        )
    )
    overrides = list(
        await session.scalars(
            select(CreditOverrideAudit)
            .where(CreditOverrideAudit.customer_id == customer_id)
            .order_by(CreditOverrideAudit.created_at.desc())
        )
    )
    notifications = list(
        await session.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.recipient_id == customer_id,
                NotificationOutbox.event_type.in_(("CREDIT_LIMIT_BLOCKED", "CREDIT_REMINDER")),
            )
            .order_by(NotificationOutbox.created_at.desc())
        )
    )
    return {
        "settingsAudit": [
            {
                "id": x.id,
                "oldLimit": x.old_limit,
                "newLimit": x.new_limit,
                "oldEnabled": x.old_enabled,
                "newEnabled": x.new_enabled,
                "reason": x.reason,
                "changedBy": x.changed_by_name,
                "createdAt": x.created_at,
            }
            for x in audits
        ],
        "overrides": [
            {
                "id": x.id,
                "amount": x.amount,
                "reason": x.reason,
                "approvedBy": x.approved_by_name,
                "expiresAt": x.expires_at,
                "consumedAt": x.consumed_at,
            }
            for x in overrides
        ],
        "notifications": [
            {
                "id": x.id,
                "type": x.event_type,
                "body": x.body,
                "sentAt": x.delivered_at,
                "status": "SENT" if x.delivered_at else "PENDING",
                "error": x.last_error,
            }
            for x in notifications
        ],
    }
