"""Shared reminder settings, follow-ups, visits and price-review actions."""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.customers.models import CustomerDeliverySite, CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant
from app.modules.reminders.engine import utc
from app.modules.reminders.models import CustomerVisit, PricingReview, Reminder
from app.modules.reminders.policies import audit, effective_rules, policy_view, save_policy
from app.modules.reminders.schemas import (
    Kind,
    PolicyUpdate,
    ReminderAction,
    ReviewInput,
    VisitInput,
)
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    get_effective_permission_service,
    require_login_channel,
)
from app.shared.authorization.permission_checker import EffectivePermissionService
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.geo.distance import haversine_metres

Session = Annotated[AsyncSession, Depends(get_db_session)]
Permissions = Annotated[EffectivePermissionService, Depends(get_effective_permission_service)]
MerchantId = Annotated[str | None, Query(alias="merchantId", max_length=36)]


def view(row):
    context = json.loads(row.context)
    return {
        "id": row.id,
        "merchantId": row.merchant_id,
        "kind": row.kind,
        "customerId": row.customer_id,
        "siteId": row.site_id,
        "assignedUserId": row.assigned_user_id,
        "subject": row.subject,
        "status": row.status,
        "reason": row.reason,
        "context": context,
        "reminderCount": row.reminder_count,
        "lastSentAt": utc(row.last_sent_at),
        "nextDueAt": utc(row.next_due_at),
        "createdAt": utc(row.created_at),
        "updatedAt": utc(row.updated_at),
    }


async def scope(session, actor, merchant_id, *, required=True):
    if actor.login_channel == LoginChannel.ADMIN:
        if required and not merchant_id:
            raise ApiError("MERCHANT_REQUIRED", 422, "Select a merchant.")
        if merchant_id and await session.get(Merchant, merchant_id) is None:
            raise ApiError("MERCHANT_NOT_FOUND", 404)
        return merchant_id
    if merchant_id:
        raise ApiError(
            "MERCHANT_SCOPE_NOT_ALLOWED", 422, "Merchant scope comes from the signed-in session."
        )
    if actor.login_channel == LoginChannel.MERCHANT:
        return actor.require_merchant_id()
    driver = await session.scalar(
        select(DeliveryProfile).where(
            DeliveryProfile.user_id == actor.user_id,
            DeliveryProfile.status == "ACTIVE",
            DeliveryProfile.approval_status == "APPROVED",
        )
    )
    if driver is None:
        raise ApiError("PERMISSION_DENIED", 403)
    return driver.merchant_id


async def authorize(permissions, actor, permission):
    if actor.login_channel != LoginChannel.DELIVERY:
        await permissions.require_permission(
            AuthContext(user_id=actor.user_id, login_channel=actor.login_channel), permission
        )


def build_router(channel):
    router = APIRouter(
        tags=[f"{channel.value.title()} Reminders"],
        dependencies=[Depends(require_login_channel(channel))],
    )

    @router.get("/settings/automations")
    async def get_settings(
        session: Session, actor: ActorDep, permissions: Permissions, merchant_id: MerchantId = None
    ):
        await authorize(
            permissions,
            actor,
            "platform_settings.view" if channel == LoginChannel.ADMIN else "delivery.view",
        )
        mid = await scope(session, actor, merchant_id, required=False)
        result = await policy_view(session, mid)
        if channel == LoginChannel.DELIVERY:
            result["rules"] = [
                {
                    "kind": r["kind"],
                    "config": {
                        k: r["config"][k]
                        for k in (
                            "enabled",
                            "radiusMeters",
                            "maxLocationAgeSeconds",
                            "maxAccuracyMeters",
                            "maxSnoozeHours",
                        )
                    },
                }
                for r in result["rules"]
                if r["kind"] in ("PROXIMITY", "VISIT")
            ]
        return result

    if channel != LoginChannel.DELIVERY:

        @router.patch("/settings/automations/{kind}")
        async def update_policy(
            kind: Kind,
            payload: PolicyUpdate,
            session: Session,
            actor: ActorDep,
            permissions: Permissions,
            merchant_id: MerchantId = None,
        ):
            await authorize(
                permissions,
                actor,
                "platform_settings.manage" if channel == LoginChannel.ADMIN else "customers.update",
            )
            mid = await scope(session, actor, merchant_id, required=False)
            return await save_policy(session, actor, kind, payload.config, mid)

    @router.get("/reminders")
    async def list_reminders(
        session: Session,
        actor: ActorDep,
        permissions: Permissions,
        merchant_id: MerchantId = None,
        kind: Kind | None = None,
        status: Annotated[
            str | None, Query(pattern="^(OPEN|ACKNOWLEDGED|SNOOZED|RESOLVED)$")
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        mid = await scope(session, actor, merchant_id)
        context = AuthContext(user_id=actor.user_id, login_channel=channel)
        query = select(Reminder).where(
            Reminder.merchant_id == mid,
            Reminder.kind != "VISIT",
            or_(Reminder.kind != "PROXIMITY", Reminder.assigned_user_id.is_(None)),
        )
        if channel == LoginChannel.DELIVERY:
            query = query.where(
                Reminder.kind == "PROXIMITY", Reminder.assigned_user_id == actor.user_id
            )
        else:
            customer_access = await permissions.has_permission(context, "customers.view")
            pricing_access = await permissions.has_permission(context, "pricing.view")
            if not customer_access and not pricing_access:
                raise ApiError("PERMISSION_DENIED", 403)
            allowed = (["PROXIMITY", "INACTIVE"] if customer_access else []) + (
                ["PRICING"] if pricing_access else []
            )
            query = query.where(Reminder.kind.in_(allowed))
        if kind:
            query = query.where(Reminder.kind == kind)
        if status:
            query = query.where(Reminder.status == status)
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await session.scalars(
                query.order_by(Reminder.updated_at.desc(), Reminder.id).limit(limit).offset(offset)
            )
        ).all()
        return {
            "items": [view(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @router.patch("/reminders/{reminder_id}")
    async def action(
        reminder_id: str,
        payload: ReminderAction,
        session: Session,
        actor: ActorDep,
        permissions: Permissions,
        merchant_id: MerchantId = None,
    ):
        mid = await scope(session, actor, merchant_id)
        await session.scalar(select(Merchant).where(Merchant.id == mid).with_for_update())
        row = await session.scalar(
            select(Reminder)
            .where(Reminder.id == reminder_id, Reminder.merchant_id == mid)
            .with_for_update()
        )
        if row is None or (
            channel == LoginChannel.DELIVERY
            and (row.kind != "PROXIMITY" or row.assigned_user_id != actor.user_id)
        ):
            raise ApiError("REMINDER_NOT_FOUND", 404)
        await authorize(
            permissions, actor, "pricing.manage" if row.kind == "PRICING" else "customers.update"
        )
        if row.status == "RESOLVED":
            raise ApiError("REMINDER_RESOLVED", 409, "This follow-up is already resolved.")
        rules, _, _ = await effective_rules(session, mid)
        now = datetime.now(UTC)
        if payload.status == "SNOOZED":
            if payload.snoozeHours is None or payload.snoozeHours > rules[row.kind].maxSnoozeHours:
                raise ApiError(
                    "INVALID_SNOOZE",
                    422,
                    "Choose a snooze duration within the configured policy limit.",
                )
            row.next_due_at = now + timedelta(hours=payload.snoozeHours)
        row.status, row.updated_at, row.reason = (
            payload.status,
            now,
            "Manually resolved." if payload.status == "RESOLVED" else None,
        )
        audit(session, actor.user_id, row.id, f"Reminder {payload.status}: {payload.note or ''}")
        await session.commit()
        return view(row)

    @router.post("/customer-visits", status_code=201)
    async def record_visit(
        payload: VisitInput,
        session: Session,
        actor: ActorDep,
        permissions: Permissions,
        merchant_id: MerchantId = None,
    ):
        mid = await scope(session, actor, merchant_id)
        await authorize(permissions, actor, "customers.update")
        await session.scalar(select(Merchant).where(Merchant.id == mid).with_for_update())
        customer = await session.get(CustomerProfile, payload.customerId)
        if customer is None or customer.merchant_id != mid:
            raise ApiError("CUSTOMER_NOT_FOUND", 404)
        now = datetime.now(UTC)
        if payload.visitedAt > now:
            raise ApiError("INVALID_VISIT_DATE", 422, "A visit cannot be recorded in the future.")
        if payload.siteId:
            site = await session.get(CustomerDeliverySite, payload.siteId)
            if site is None or site.customer_id != customer.id or not site.is_active:
                raise ApiError("SITE_NOT_FOUND", 404)
            latitude, longitude = site.latitude, site.longitude
        else:
            latitude, longitude = customer.address_latitude, customer.address_longitude
        existing = await session.scalar(
            select(CustomerVisit)
            .where(
                CustomerVisit.merchant_id == mid,
                CustomerVisit.idempotency_key == payload.idempotencyKey,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing:
            if (
                existing.user_id != actor.user_id
                or existing.customer_id != payload.customerId
                or existing.site_id != payload.siteId
                or existing.outcome != payload.outcome
                or utc(existing.visited_at) != payload.visitedAt
                or existing.notes != payload.notes
            ):
                raise ApiError(
                    "VISIT_CONFLICT", 409, "This visit key was already used for different data."
                )
            return {"id": existing.id, "verification": existing.verification}
        if channel == LoginChannel.DELIVERY:
            allowed = await session.scalar(
                select(Reminder.id)
                .where(
                    Reminder.merchant_id == mid,
                    Reminder.customer_id == customer.id,
                    Reminder.kind == "PROXIMITY",
                    Reminder.site_id == payload.siteId,
                    Reminder.assigned_user_id == actor.user_id,
                    Reminder.status != "RESOLVED",
                )
                .limit(1)
            )
            if allowed is None:
                raise ApiError(
                    "PERMISSION_DENIED",
                    403,
                    "Drivers may record visits only for their assigned active follow-ups.",
                )
        rules, _, _ = await effective_rules(session, mid)
        rule = rules["PROXIMITY"]
        verification = "MANUAL"
        if (
            payload.latitude is not None
            and latitude is not None
            and longitude is not None
            and payload.accuracy is not None
        ):
            recent = (now - payload.visitedAt).total_seconds() <= rule.maxLocationAgeSeconds
            if (
                recent
                and payload.accuracy <= rule.maxAccuracyMeters
                and haversine_metres(
                    payload.latitude, payload.longitude, float(latitude), float(longitude)
                )
                <= rule.radiusMeters
            ):
                verification = "LOCATION_MATCH"
        row = CustomerVisit(
            id=str(uuid4()),
            merchant_id=mid,
            customer_id=customer.id,
            site_id=payload.siteId,
            user_id=actor.user_id,
            idempotency_key=payload.idempotencyKey,
            outcome=payload.outcome,
            notes=payload.notes,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
            verification=verification,
            visited_at=payload.visitedAt.astimezone(UTC),
            created_at=now,
        )
        session.add(row)
        if payload.outcome == "VISITED":
            for reminder in (
                await session.scalars(
                    select(Reminder).where(
                        Reminder.merchant_id == mid,
                        Reminder.customer_id == customer.id,
                        Reminder.site_id == payload.siteId,
                        Reminder.kind.in_(["VISIT", "PROXIMITY"]),
                        Reminder.status != "RESOLVED",
                    )
                )
            ).all():
                # A backdated offline visit cannot clear a follow-up for newer activity.
                baseline = json.loads(reminder.context).get("baseline")
                if not baseline or payload.visitedAt >= datetime.fromisoformat(baseline):
                    reminder.status, reminder.reason, reminder.updated_at = (
                        "RESOLVED",
                        "Visit completed.",
                        now,
                    )
        audit(
            session,
            actor.user_id,
            row.id,
            f"Customer visit {payload.outcome}; verification={verification}",
        )
        await session.commit()
        return {"id": row.id, "verification": verification}

    if channel != LoginChannel.DELIVERY:

        @router.post("/pricing/reviews", status_code=201)
        async def reviewed(
            payload: ReviewInput,
            session: Session,
            actor: ActorDep,
            permissions: Permissions,
            merchant_id: MerchantId = None,
        ):
            mid = await scope(session, actor, merchant_id)
            await authorize(permissions, actor, "pricing.manage")
            await session.scalar(select(Merchant).where(Merchant.id == mid).with_for_update())
            row = PricingReview(
                id=str(uuid4()),
                merchant_id=mid,
                month=payload.month,
                user_id=actor.user_id,
                note=payload.note,
                reviewed_at=datetime.now(UTC),
            )
            session.add(row)
            for reminder in (
                await session.scalars(
                    select(Reminder).where(
                        Reminder.merchant_id == mid,
                        Reminder.kind == "PRICING",
                        Reminder.status != "RESOLVED",
                    )
                )
            ).all():
                data = json.loads(reminder.context)
                if data.get("month") == payload.month and data.get("trigger") == "REVIEW":
                    reminder.status, reminder.reason, reminder.updated_at = (
                        "RESOLVED",
                        "Pricing reviewed.",
                        row.reviewed_at,
                    )
            audit(
                session,
                actor.user_id,
                row.id,
                f"Pricing {payload.month} reviewed: {payload.note or 'no changes'}",
            )
            await session.commit()
            return {"id": row.id, "month": row.month}

    return router
