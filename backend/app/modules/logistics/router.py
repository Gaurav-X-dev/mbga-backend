import json
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import get_settings
from app.modules.authentication.constants import LoginChannel
from app.modules.business_catalogue.models import CylinderTypeDefinition
from app.modules.customers.dependencies import ActorDep
from app.modules.customers.models import CustomerProfile
from app.modules.deliveries.models import DeliverySlip
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.finance.settings import audit
from app.modules.logistics.models import LogisticsSettings, Trip, TripStop
from app.modules.logistics.policy import policy
from app.modules.logistics.routing import optimize
from app.modules.logistics.schemas import (
    SequenceUpdate,
    SettingsUpdate,
    TripAction,
    TripCreate,
    Versioned,
)
from app.modules.logistics.service import TripService
from app.modules.merchants.models import Merchant
from app.modules.orders.models import Order
from app.shared.authorization.dependencies import (
    get_effective_permission_service,
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

Session = Annotated[AsyncSession, Depends(get_db_session)]


async def commit(session):
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "TRIP_CONFLICT", 409, "Trip or delivery changed. Refresh before retrying."
        ) from exc


def build_router(channel):
    driver = channel == LoginChannel.DELIVERY
    guards = [Depends(require_login_channel(channel))]
    if channel == LoginChannel.ADMIN:
        guards.append(Depends(require_permission("merchants.view")))
    router = APIRouter(
        prefix="/trips", tags=[f"{channel.value.title()} Trips"], dependencies=guards
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
        Annotated[object, Depends(driver_actor)]
        if driver
        else AdminMerchantActorDep
        if channel == LoginChannel.ADMIN
        else ActorDep
    )

    def service(session: Session, actor: Actor, settings: Annotated[object, Depends(get_settings)]):
        return TripService(session, actor, settings, driver)

    Service = Annotated[TripService, Depends(service)]
    read = [] if driver else [Depends(require_permission("delivery.view"))]
    write = [Depends(require_permission("delivery.confirm"))]

    @router.get("/options")
    async def options(service: Service):
        config = await policy(service.session, service.merchant_id)
        cylinders = (
            await service.session.scalars(
                select(CylinderTypeDefinition)
                .where(CylinderTypeDefinition.is_active.is_(True))
                .order_by(CylinderTypeDefinition.sort_order)
            )
        ).all()
        return {
            "policy": config.model_dump(),
            "routingConfigured": bool(service.settings.logistics_routes_api_key),
            "cylinders": [{"code": c.code, "label": c.label} for c in cylinders],
        }

    @router.get("", dependencies=read)
    async def trips(
        service: Service,
        status: Annotated[str | None, Query(max_length=24)] = None,
        vehicle: Annotated[str | None, Query(max_length=50)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        query = select(Trip).where(Trip.merchant_id == service.merchant_id)
        if driver:
            query = query.where(Trip.driver_user_id == service.actor.user_id)
        if status:
            query = query.where(
                Trip.status.in_(("DRAFT", "READY", "IN_PROGRESS", "RETURNED", "DISCREPANCY"))
                if status == "ACTIVE"
                else Trip.status == status
            )
        if vehicle:
            query = query.where(Trip.vehicle_number == vehicle)
        total = await service.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await service.session.scalars(
                query.order_by(Trip.created_at.desc(), Trip.id).limit(limit).offset(offset)
            )
        ).all()
        return {"items": await service.views(rows), "total": total}

    if not driver:

        @router.get("/candidates", dependencies=read)
        async def candidates(
            service: Service,
            search: Annotated[str | None, Query(max_length=120)] = None,
            priority: Annotated[str | None, Query(alias="priorityCode", max_length=30)] = None,
            delivery_date: Annotated[date | None, Query(alias="deliveryDate")] = None,
            limit: Annotated[int, Query(ge=1, le=50)] = 20,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            query = select(DeliverySlip).where(
                DeliverySlip.merchant_id == service.merchant_id,
                DeliverySlip.status == "SCHEDULED",
                ~DeliverySlip.id.in_(select(TripStop.delivery_id)),
            )
            if priority:
                from app.modules.logistics.policy import priority_code

                await priority_code(service.session, service.merchant_id, priority)
                query = query.where(
                    DeliverySlip.order_id.in_(
                        select(Order.id).where(Order.priority_code == priority)
                    )
                )
            if delivery_date:
                query = query.where(DeliverySlip.scheduled_date == delivery_date)
            if search:
                term = "%" + search.strip() + "%"
                query = query.where(
                    or_(
                        DeliverySlip.customer_name.ilike(term),
                        DeliverySlip.order_number.ilike(term),
                        DeliverySlip.vehicle_number.ilike(term),
                        DeliverySlip.driver_name.ilike(term),
                    )
                )
            total = await service.session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await service.session.scalars(
                    query.order_by(DeliverySlip.scheduled_date, DeliverySlip.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            priorities = (
                dict(
                    (
                        await service.session.execute(
                            select(Order.id, Order.priority_code).where(
                                Order.id.in_([s.order_id for s in rows])
                            )
                        )
                    ).all()
                )
                if rows
                else {}
            )
            return {
                "items": [
                    {
                        "deliveryId": s.id,
                        "priorityCode": priorities.get(s.order_id),
                        "orderNumber": s.order_number,
                        "customerName": s.customer_name,
                        "vehicleNumber": s.vehicle_number,
                        "driverUserId": s.driver_user_id,
                        "driverName": s.driver_name,
                        "date": str(s.scheduled_date),
                        "itemsSummary": s.items_summary,
                    }
                    for s in rows
                ],
                "total": total,
            }

    @router.get("/{trip_id}", dependencies=read)
    async def detail(trip_id: str, service: Service):
        return await service.view(await service.owned(trip_id))

    if not driver:

        @router.post("", status_code=201, dependencies=write)
        async def create(payload: TripCreate, service: Service):
            row = await service.create(payload)
            await commit(service.session)
            return await service.view(row)

        @router.patch("/{trip_id}/sequence", dependencies=write)
        async def sequence(trip_id: str, payload: SequenceUpdate, service: Service):
            row = await service.owned(trip_id, True)
            await service.sequence(row, payload)
            await commit(service.session)
            return await service.view(row)

        @router.post("/{trip_id}/optimize", dependencies=write)
        async def route(trip_id: str, payload: Versioned, service: Service):
            row = await service.owned(trip_id, True)
            service.check_version(row, payload.expectedVersion)
            preview = await optimize(service, row)
            service.changed(row, "Route optimization preview: " + payload.reason)
            preview["basedOnVersion"] = row.version
            row.route_preview = json.dumps(preview)
            await commit(service.session)
            return await service.view(row)

    @router.post("/{trip_id}/actions", dependencies=[] if driver else write)
    async def action(
        trip_id: str,
        payload: TripAction,
        service: Service,
        context: Annotated[object, Depends(require_authenticated_user)],
        permissions: Annotated[object, Depends(get_effective_permission_service)],
    ):
        if payload.action == "RESOLVE":
            await permissions.require_permission(context, "inventory.adjust")
        row = await service.owned(trip_id, True)
        await service.action(row, payload)
        await commit(service.session)
        return await service.view(row)

    return router


settings_router = APIRouter(
    prefix="/logistics/settings",
    tags=["Logistics Settings"],
    dependencies=[
        Depends(require_login_channel(LoginChannel.ADMIN)),
        Depends(require_permission("platform_settings.view")),
    ],
)


@settings_router.get("")
async def settings(
    session: Session,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
):
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    return {
        "config": (await policy(session, merchant_id or "platform")).model_dump(),
        "routingConfigured": bool(get_settings().logistics_routes_api_key),
    }


@settings_router.patch("", dependencies=[Depends(require_permission("platform_settings.manage"))])
async def save_settings(
    payload: SettingsUpdate,
    session: Session,
    actor: ActorDep,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
):
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404)
    scope = merchant_id or "platform"
    if merchant_id:
        await session.scalar(select(Merchant).where(Merchant.id == merchant_id).with_for_update())
    row = await session.scalar(
        select(LogisticsSettings).where(LogisticsSettings.scope == scope).with_for_update()
    )
    if payload.config is None:
        if not merchant_id:
            raise ApiError("INVALID_SETTINGS", 422, "Platform defaults cannot be cleared.")
        if row:
            await session.delete(row)
    else:
        codes = [p.code for p in payload.config.priorities]
        overrides = select(LogisticsSettings.scope).where(LogisticsSettings.scope != "platform")
        for model in (CustomerProfile, Order):
            scope_filter = (
                model.merchant_id == merchant_id
                if merchant_id
                else ~model.merchant_id.in_(overrides)
            )
            if await session.scalar(
                select(model.id)
                .where(
                    scope_filter, model.priority_code.is_not(None), ~model.priority_code.in_(codes)
                )
                .limit(1)
            ):
                raise ApiError(
                    "PRIORITY_IN_USE",
                    409,
                    "Keep codes that are referenced by customers or orders; edit their label/rank instead.",
                )
        if row is None:
            row = LogisticsSettings(scope=scope, updated_at=datetime.now(UTC))
            session.add(row)
        row.config = payload.config.model_dump_json()
        row.updated_by = actor.user_id
        row.updated_at = datetime.now(UTC)
    audit(session, actor.user_id, merchant_id, "Logistics policy updated for " + scope)
    await commit(session)
    return {"config": (await policy(session, scope)).model_dump()}
