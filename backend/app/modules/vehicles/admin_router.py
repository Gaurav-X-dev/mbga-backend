"""The merchant's own list of vans (merchant channel only).

Managed from the panel rather than typed into every assignment. The assignment form reads this
list, and `DeliveryService` checks what it is given against it, so the two cannot disagree about
which vans exist.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.deliveries import validation as delivery_validation
from app.modules.vehicles.coverage import list_pincodes, replace_pincodes
from app.modules.vehicles.models import Vehicle
from app.modules.vehicles.schemas import (
    VehicleCreate,
    VehicleListResponse,
    VehiclePincodeReplaceRequest,
    VehiclePincodeResponse,
    VehicleResponse,
    VehicleUpdate,
)
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

router = APIRouter(prefix="/vehicles", tags=["Admin Merchant Vehicles"])

_admin_only = Depends(require_login_channel(LoginChannel.ADMIN))
_merchant_scope = Depends(require_permission("merchants.view"))
#: A van is part of running deliveries, so it is the dispatch permissions that govern it rather
#: than a set of its own - the people who assign vehicles are the people who maintain the list.
#: `delivery.*` is the merchant's pair; `deliveries.*` belongs to the driver app.
_read = [_admin_only, _merchant_scope, Depends(require_permission("delivery.view"))]
_write = [_admin_only, _merchant_scope, Depends(require_permission("delivery.confirm"))]

VehicleIdPath = Annotated[str, Path(alias="vehicleId", max_length=36)]


def _view(vehicle: Vehicle) -> VehicleResponse:
    return VehicleResponse(
        id=vehicle.id,
        number=vehicle.number,
        label=vehicle.label,
        notes=vehicle.notes,
        is_active=vehicle.is_active,
        created_at=vehicle.created_at,
    )


async def _owned(session: AsyncSession, merchant_id: str, vehicle_id: str) -> Vehicle:
    """This merchant's vehicle, or a 404. Another merchant's is indistinguishable from absent."""
    vehicle = await session.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.merchant_id == merchant_id)
    )
    if vehicle is None:
        raise ApiError(
            "VEHICLE_NOT_FOUND", status.HTTP_404_NOT_FOUND, "We could not find this vehicle."
        )
    return vehicle


@router.get("", response_model=VehicleListResponse, dependencies=_read)
async def list_vehicles(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
    active_only: Annotated[
        bool, Query(alias="activeOnly", description="Only vans that may be assigned today.")
    ] = False,
    search: str | None = None,
) -> VehicleListResponse:
    """Every van this merchant has, newest first.

    `activeOnly` is what the assignment dropdown asks for; the management screen wants the
    retired ones too, so they can be brought back.
    """
    merchant_id = actor.require_merchant_id()
    filters = [Vehicle.merchant_id == merchant_id]
    if active_only:
        filters.append(Vehicle.is_active.is_(True))
    if search:
        filters.append(func.lower(Vehicle.number).like(f"%{search.lower()}%"))
    rows = list(
        await session.scalars(
            select(Vehicle).where(*filters).order_by(Vehicle.is_active.desc(), Vehicle.number)
        )
    )
    return VehicleListResponse(items=[_view(row) for row in rows], total=len(rows))


@router.get("/available", response_model=VehicleListResponse, dependencies=_read)
async def list_available_vehicles(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> VehicleListResponse:
    """The assignment dropdown's list: the vans that may be assigned today.

    The same rows as `?activeOnly=true`, under the name the assignment screen asks for. Kept
    as its own route rather than left to the query flag because the screen reaching for it got
    a 405 - `/vehicles/{vehicleId}` matched `available` as an id, and GET is not a verb that
    path has.

    Declared **before** `/{vehicleId}`, so the literal path wins the match.
    """
    return await list_vehicles(session, actor, active_only=True, search=None)


@router.post(
    "", response_model=VehicleResponse, status_code=status.HTTP_201_CREATED, dependencies=_write
)
async def create_vehicle(
    payload: VehicleCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> VehicleResponse:
    """Add a van.

    The number is normalised the same way an assignment normalises it, so `mp09gh4521` and
    `MP09 GH 4521` cannot both be added - they are one van, and two rows for it would let a
    driver be sent out twice in it.
    """
    merchant_id = actor.require_merchant_id()
    number = delivery_validation.check_vehicle_number(payload.number)
    now = datetime.now(UTC)
    vehicle = Vehicle(
        id=str(uuid4()),
        merchant_id=merchant_id,
        number=number,
        label=(payload.label or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(vehicle)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "VEHICLE_ALREADY_EXISTS",
            status.HTTP_409_CONFLICT,
            f"{number} is already on this merchant's list.",
        ) from exc
    return _view(vehicle)


@router.patch("/{vehicleId}", response_model=VehicleResponse, dependencies=_write)
async def update_vehicle(
    vehicle_id: VehicleIdPath,
    payload: VehicleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> VehicleResponse:
    """Rename, re-plate, or take a van off the road.

    `isActive: false` is how a van is retired. It is never deleted: every slip it carried still
    names it, and those slips have to keep reading.
    """
    merchant_id = actor.require_merchant_id()
    vehicle = await _owned(session, merchant_id, vehicle_id)
    updates = payload.model_dump(exclude_unset=True)
    if "number" in updates:
        vehicle.number = delivery_validation.check_vehicle_number(updates["number"])
    for field in ("label", "notes"):
        if field in updates:
            setattr(vehicle, field, (updates[field] or "").strip() or None)
    if "is_active" in updates:
        vehicle.is_active = bool(updates["is_active"])
    vehicle.updated_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "VEHICLE_ALREADY_EXISTS",
            status.HTTP_409_CONFLICT,
            f"{vehicle.number} is already on this merchant's list.",
        ) from exc
    return _view(vehicle)


@router.get("/{vehicleId}/pincodes", response_model=VehiclePincodeResponse, dependencies=_read)
async def get_vehicle_pincodes(
    vehicle_id: VehicleIdPath,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> VehiclePincodeResponse:
    return await list_pincodes(session, actor.require_merchant_id(), vehicle_id)


@router.put("/{vehicleId}/pincodes", response_model=VehiclePincodeResponse, dependencies=_write)
async def put_vehicle_pincodes(
    vehicle_id: VehicleIdPath,
    payload: VehiclePincodeReplaceRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: AdminMerchantActorDep,
) -> VehiclePincodeResponse:
    return await replace_pincodes(
        session, actor.require_merchant_id(), vehicle_id, payload.pincodes
    )
