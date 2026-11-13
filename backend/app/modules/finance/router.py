from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep, CustomerActorDep
from app.modules.customers.models import CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.finance import advances, cash
from app.modules.finance.models import (
    AdvanceDeposit,
    AdvanceEntry,
    CashCustody,
    CashHandover,
    CashHandoverItem,
    FinanceSettings,
)
from app.modules.finance.schemas import (
    DepositInput,
    DepositVerification,
    HandoverInput,
    HandoverVerification,
    RefundInput,
    SettingsUpdate,
)
from app.modules.finance.settings import audit, policy
from app.modules.merchants.models import Merchant
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.date_time.business_calendar import business_day_window
from app.shared.exceptions.api_error import ApiError

Session = Annotated[AsyncSession, Depends(get_db_session)]


def stamp(value):
    return (
        (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()
        if value
        else None
    )


def deposit_view(row):
    return {
        "id": row.id,
        "customerId": row.customer_id,
        "amount": row.amount,
        "mode": row.mode,
        "reference": row.reference,
        "status": row.status,
        "notes": row.notes,
        "createdAt": stamp(row.created_at),
        "verifiedAt": stamp(row.verified_at),
    }


def ledger_view(row):
    return {
        "id": row.id,
        "kind": row.kind,
        "amount": row.amount,
        "balanceAfter": row.balance_after,
        "reference": row.reference,
        "orderId": row.order_id,
        "paymentId": row.payment_id,
        "notes": row.notes,
        "createdAt": stamp(row.created_at),
    }


def batch_view(row):
    return {
        "id": row.id,
        "driverId": row.driver_id,
        "expectedAmount": row.expected_amount,
        "receivedAmount": row.received_amount,
        "difference": row.difference,
        "status": row.status,
        "notes": row.notes,
        "verificationNotes": row.verification_notes,
        "createdBy": row.created_by,
        "verifiedBy": row.verified_by,
        "createdAt": stamp(row.created_at),
        "verifiedAt": stamp(row.verified_at),
    }


async def commit(session):
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "FINANCE_CONFLICT",
            409,
            "Reference or request already exists, or the balance changed. Refresh before retrying.",
        ) from exc


def build_router(channel):
    is_customer = channel == LoginChannel.CUSTOMER
    is_driver = channel == LoginChannel.DELIVERY
    admin = channel == LoginChannel.ADMIN
    guards = [Depends(require_login_channel(channel))]
    if admin:
        guards.append(Depends(require_permission("merchants.view")))
    router = APIRouter(
        prefix="/finance", tags=[f"{channel.value.title()} Finance"], dependencies=guards
    )

    async def driver_actor(actor: ActorDep, session: Session):
        profile = await session.scalar(
            select(DeliveryProfile).where(
                DeliveryProfile.user_id == actor.user_id,
                DeliveryProfile.status == "ACTIVE",
                DeliveryProfile.approval_status == "APPROVED",
            )
        )
        if profile is None:
            raise ApiError("PERMISSION_DENIED", 403)
        return replace(actor, merchant_id=profile.merchant_id)

    Actor = (
        CustomerActorDep
        if is_customer
        else Annotated[object, Depends(driver_actor)]
        if is_driver
        else AdminMerchantActorDep
        if admin
        else ActorDep
    )
    reads = [] if is_customer or is_driver else [Depends(require_permission("payments.view"))]

    async def customer_row(session, actor, customer_id):
        wanted = actor.customer_id if is_customer else customer_id
        if not wanted:
            raise ApiError("CUSTOMER_REQUIRED", 422, "Select a customer.")
        if is_customer and customer_id and customer_id != wanted:
            raise ApiError("CUSTOMER_NOT_FOUND", 404)
        row = await session.get(CustomerProfile, wanted)
        if row is None or row.merchant_id != actor.merchant_id:
            raise ApiError("CUSTOMER_NOT_FOUND", 404)
        return row

    if not is_driver:

        @router.get("/advance", dependencies=reads)
        async def balance(
            session: Session,
            actor: Actor,
            customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
        ):
            customer = await customer_row(session, actor, customer_id)
            return await advances.summary(session, customer.id, actor.merchant_id)

        @router.get("/advance/ledger", dependencies=reads)
        async def ledger(
            session: Session,
            actor: Actor,
            customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 25,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            customer = await customer_row(session, actor, customer_id)
            query = select(AdvanceEntry).where(
                AdvanceEntry.merchant_id == actor.merchant_id,
                AdvanceEntry.customer_id == customer.id,
            )
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.scalars(
                    query.order_by(AdvanceEntry.created_at.desc(), AdvanceEntry.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return {"items": [ledger_view(r) for r in rows], "total": total}

        @router.get("/advance/deposits", dependencies=reads)
        async def deposits(
            session: Session,
            actor: Actor,
            customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
            status: Annotated[str | None, Query(pattern="^(PENDING|VERIFIED|REJECTED)$")] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 25,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            query = select(AdvanceDeposit).where(AdvanceDeposit.merchant_id == actor.merchant_id)
            if is_customer or customer_id:
                customer = await customer_row(session, actor, customer_id)
                query = query.where(AdvanceDeposit.customer_id == customer.id)
            if status:
                query = query.where(AdvanceDeposit.status == status)
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.scalars(
                    query.order_by(AdvanceDeposit.created_at.desc(), AdvanceDeposit.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            names = (
                dict(
                    (
                        await session.execute(
                            select(CustomerProfile.id, CustomerProfile.name).where(
                                CustomerProfile.id.in_([r.customer_id for r in rows]),
                                CustomerProfile.merchant_id == actor.merchant_id,
                            )
                        )
                    ).all()
                )
                if rows
                else {}
            )
            return {
                "items": [
                    {**deposit_view(r), "customerName": names.get(r.customer_id)} for r in rows
                ],
                "total": total,
            }

        @router.post(
            "/advance/deposits",
            status_code=201,
            dependencies=[] if is_customer else [Depends(require_permission("payments.collect"))],
        )
        async def deposit(payload: DepositInput, session: Session, actor: Actor):
            customer = await customer_row(session, actor, payload.customerId)
            row = await advances.request_deposit(session, actor, payload, customer)
            await commit(session)
            return deposit_view(row)

    if not is_customer and not is_driver:

        @router.post(
            "/advance/deposits/{deposit_id}/verify",
            dependencies=[Depends(require_permission("payments.reconcile"))],
        )
        async def verify_deposit(
            deposit_id: str, payload: DepositVerification, session: Session, actor: Actor
        ):
            row = await advances.verify_deposit(
                session, actor, deposit_id, payload.verified, payload.reason
            )
            await commit(session)
            return deposit_view(row)

        @router.post(
            "/advance/refunds",
            status_code=201,
            dependencies=[Depends(require_permission("payments.reconcile"))],
        )
        async def record_refund(payload: RefundInput, session: Session, actor: Actor):
            await customer_row(session, actor, payload.customerId)
            row = await advances.refund(session, actor, payload)
            await commit(session)
            return ledger_view(row)

    if not is_customer:

        async def driver_id_for(session, actor, wanted):
            if is_driver:
                row = await session.scalar(
                    select(DeliveryProfile).where(
                        DeliveryProfile.user_id == actor.user_id,
                        DeliveryProfile.merchant_id == actor.merchant_id,
                    )
                )
                if wanted and wanted != row.id:
                    raise ApiError("PERMISSION_DENIED", 403)
                return row.id
            return wanted

        @router.get("/cash-collections", dependencies=reads)
        async def collections(
            session: Session,
            actor: Actor,
            driver_id: Annotated[str | None, Query(alias="driverId", max_length=36)] = None,
            vehicle: Annotated[str | None, Query(max_length=50)] = None,
            invoice: Annotated[str | None, Query(max_length=40)] = None,
            date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
            date_to: Annotated[date | None, Query(alias="dateTo")] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 50,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            driver_id = await driver_id_for(session, actor, driver_id)
            if date_from and date_to and date_from > date_to:
                raise ApiError("INVALID_DATE_RANGE", 422)
            query = select(CashCustody).where(
                CashCustody.merchant_id == actor.merchant_id,
                CashCustody.cash_amount > CashCustody.received_amount,
            )
            if driver_id:
                query = query.where(CashCustody.driver_id == driver_id)
            if vehicle:
                query = query.where(CashCustody.vehicle_number == vehicle)
            if invoice:
                query = query.where(CashCustody.invoice_number == invoice)
            if date_from:
                query = query.where(CashCustody.collected_at >= business_day_window(date_from)[0])
            if date_to:
                query = query.where(CashCustody.collected_at < business_day_window(date_to)[1])
            table = query.subquery()
            totals = (
                await session.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(table.c.cash_amount - table.c.received_amount), 0),
                    ).select_from(table)
                )
            ).one()
            rows = (
                await session.scalars(
                    query.order_by(CashCustody.collected_at, CashCustody.payment_id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            claims = await cash.pending_claims(session, [r.payment_id for r in rows])
            driver_query = select(CashCustody.driver_id, CashCustody.driver_name).where(
                CashCustody.merchant_id == actor.merchant_id,
                CashCustody.cash_amount > CashCustody.received_amount,
            )
            if is_driver:
                driver_query = driver_query.where(CashCustody.driver_id == driver_id)
            drivers = (
                await session.execute(driver_query.distinct().order_by(CashCustody.driver_name))
            ).all()
            return {
                "drivers": [{"id": identifier, "name": name} for identifier, name in drivers],
                "items": [
                    {
                        "id": r.payment_id,
                        "driverId": r.driver_id,
                        "driverName": r.driver_name,
                        "vehicle": r.vehicle_number,
                        "invoice": r.invoice_number,
                        "cashAmount": r.cash_amount,
                        "receivedAmount": r.received_amount,
                        "remaining": r.cash_amount - r.received_amount,
                        "submittedAmount": int(claims.get(r.payment_id, 0)),
                        "collectedAt": stamp(r.collected_at),
                    }
                    for r in rows
                ],
                "total": totals[0],
                "cashInCustody": int(totals[1]),
                "coverage": "Collections captured since finance deployment; historical cash is not assumed outstanding.",
            }

        @router.get("/cash-handovers", dependencies=reads)
        async def handovers(
            session: Session,
            actor: Actor,
            driver_id: Annotated[str | None, Query(alias="driverId", max_length=36)] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 25,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            driver_id = await driver_id_for(session, actor, driver_id)
            query = select(CashHandover).where(CashHandover.merchant_id == actor.merchant_id)
            if driver_id:
                query = query.where(CashHandover.driver_id == driver_id)
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.scalars(
                    query.order_by(CashHandover.created_at.desc(), CashHandover.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            pairs = (
                (
                    await session.execute(
                        select(CashHandoverItem, CashCustody)
                        .join(CashCustody, CashCustody.payment_id == CashHandoverItem.payment_id)
                        .where(CashHandoverItem.handover_id.in_([r.id for r in rows]))
                    )
                ).all()
                if rows
                else []
            )
            settings = await policy(session, actor.merchant_id)
            driver_users = (
                dict(
                    (
                        await session.execute(
                            select(DeliveryProfile.id, DeliveryProfile.user_id).where(
                                DeliveryProfile.id.in_([r.driver_id for r in rows]),
                                DeliveryProfile.merchant_id == actor.merchant_id,
                            )
                        )
                    ).all()
                )
                if rows
                else {}
            )
            items = []
            for row in rows:
                item = batch_view(row)
                item["verificationBlockedReason"] = (
                    "Only an authorized office user can verify cash."
                    if is_driver
                    else "You collected this cash as the driver. Another authorized office user must verify or reject it."
                    if driver_users.get(row.driver_id) == actor.user_id
                    else "Separate office verification is enabled. Another office user must verify or reject your submission."
                    if settings.requireSeparateVerifier and row.created_by == actor.user_id
                    else None
                )
                item["items"] = [
                    {
                        "paymentId": i.payment_id,
                        "invoice": c.invoice_number,
                        "vehicle": c.vehicle_number,
                        "driverName": c.driver_name,
                        "expectedAmount": i.expected_amount,
                        "receivedAmount": i.received_amount,
                    }
                    for i, c in pairs
                    if i.handover_id == row.id
                ]
                items.append(item)
            return {"items": items, "total": total}

        @router.post(
            "/cash-handovers",
            status_code=201,
            dependencies=[] if is_driver else [Depends(require_permission("payments.collect"))],
        )
        async def submit(payload: HandoverInput, session: Session, actor: Actor):
            wanted = await driver_id_for(session, actor, payload.driverId)
            if not wanted:
                raise ApiError("DRIVER_REQUIRED", 422)
            row = await cash.submit(session, actor, payload, wanted)
            await commit(session)
            return batch_view(row)

        if not is_driver:

            @router.post(
                "/cash-handovers/{handover_id}/verify",
                dependencies=[Depends(require_permission("payments.reconcile"))],
            )
            async def verify(
                handover_id: str, payload: HandoverVerification, session: Session, actor: Actor
            ):
                row = await cash.verify(session, actor, handover_id, payload)
                await commit(session)
                return batch_view(row)

    return router


settings_router = APIRouter(
    prefix="/finance/settings",
    tags=["Finance Settings"],
    dependencies=[
        Depends(require_login_channel(LoginChannel.ADMIN)),
        Depends(require_permission("platform_settings.view")),
    ],
)


@settings_router.get("")
async def read_settings(
    session: Session,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
):
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    return {
        "merchantId": merchant_id,
        "config": (await policy(session, merchant_id or "platform")).model_dump(),
    }


@settings_router.patch("", dependencies=[Depends(require_permission("platform_settings.manage"))])
async def update_settings(
    payload: SettingsUpdate,
    session: Session,
    actor: ActorDep,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
):
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    scope = merchant_id or "platform"
    row = await session.scalar(
        select(FinanceSettings).where(FinanceSettings.scope == scope).with_for_update()
    )
    if payload.config is None:
        if not merchant_id:
            raise ApiError("INVALID_SETTINGS", 422, "Platform defaults cannot be removed.")
        if row:
            await session.delete(row)
    else:
        if row is None:
            # Scope lock serializes first merchant-override creation.
            await session.scalar(
                select(Merchant).where(Merchant.id == merchant_id).with_for_update()
            )
            row = await session.scalar(
                select(FinanceSettings).where(FinanceSettings.scope == scope).with_for_update()
            )
            if row is None:
                row = FinanceSettings(
                    scope=scope,
                    config=payload.config.model_dump_json(),
                    updated_at=datetime.now(UTC),
                )
                session.add(row)
        row.config, row.updated_by, row.updated_at = (
            payload.config.model_dump_json(),
            actor.user_id,
            datetime.now(UTC),
        )
    audit(session, actor.user_id, merchant_id, "Finance settings updated for " + scope)
    await commit(session)
    return {"merchantId": merchant_id, "config": (await policy(session, scope)).model_dump()}
