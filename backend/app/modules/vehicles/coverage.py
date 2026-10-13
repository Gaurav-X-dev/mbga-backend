"""Vehicle delivery-area operations shared by merchant and admin channels."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.models import DeliverySlip
from app.modules.locations.models import PostalLocation
from app.modules.vehicles.models import Vehicle, VehiclePincodeMapping
from app.modules.vehicles.schemas import AvailableVehicleResponse, VehiclePincodeResponse
from app.shared.exceptions.api_error import ApiError

PINCODE = re.compile(r"^\d{6}$")


async def owned_vehicle(session: AsyncSession, merchant_id: str, vehicle_id: str) -> Vehicle:
    vehicle = await session.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.merchant_id == merchant_id)
    )
    if vehicle is None:
        raise ApiError(
            "VEHICLE_NOT_FOUND", status.HTTP_404_NOT_FOUND, "We could not find this vehicle."
        )
    return vehicle


async def replace_pincodes(
    session: AsyncSession, merchant_id: str, vehicle_id: str, pincodes: list[str]
) -> VehiclePincodeResponse:
    await owned_vehicle(session, merchant_id, vehicle_id)
    cleaned = sorted({str(pin).strip() for pin in pincodes})
    invalid = [pin for pin in cleaned if not PINCODE.fullmatch(pin)]
    if invalid:
        raise ApiError(
            "INVALID_PINCODE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid pincode: {invalid[0]}",
        )
    known = (
        set(
            await session.scalars(
                select(PostalLocation.pincode).where(
                    PostalLocation.pincode.in_(cleaned), PostalLocation.is_active.is_(True)
                )
            )
        )
        if cleaned
        else set()
    )
    unknown = [pin for pin in cleaned if pin not in known]
    if unknown:
        raise ApiError(
            "PINCODE_NOT_FOUND",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Pincode is not in postal master: {unknown[0]}",
        )
    await session.execute(
        delete(VehiclePincodeMapping).where(
            VehiclePincodeMapping.vehicle_id == vehicle_id,
            VehiclePincodeMapping.merchant_id == merchant_id,
        )
    )
    now = datetime.now(UTC)
    for priority, pincode in enumerate(cleaned):
        session.add(
            VehiclePincodeMapping(
                id=str(uuid4()),
                merchant_id=merchant_id,
                vehicle_id=vehicle_id,
                pincode=pincode,
                priority=priority,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()
    return VehiclePincodeResponse(vehicle_id=vehicle_id, pincodes=cleaned)


async def list_pincodes(
    session: AsyncSession, merchant_id: str, vehicle_id: str
) -> VehiclePincodeResponse:
    await owned_vehicle(session, merchant_id, vehicle_id)
    rows = list(
        await session.scalars(
            select(VehiclePincodeMapping.pincode)
            .where(
                VehiclePincodeMapping.vehicle_id == vehicle_id,
                VehiclePincodeMapping.merchant_id == merchant_id,
                VehiclePincodeMapping.is_active.is_(True),
            )
            .order_by(VehiclePincodeMapping.priority, VehiclePincodeMapping.pincode)
        )
    )
    return VehiclePincodeResponse(vehicle_id=vehicle_id, pincodes=rows)


async def available_for_delivery(
    session: AsyncSession, merchant_id: str, delivery_id: str
) -> list[AvailableVehicleResponse]:
    slip = await session.scalar(
        select(DeliverySlip).where(
            DeliverySlip.id == delivery_id, DeliverySlip.merchant_id == merchant_id
        )
    )
    if slip is None:
        raise ApiError("DELIVERY_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if not slip.address_pincode:
        raise ApiError(
            "DELIVERY_PINCODE_MISSING", status.HTTP_409_CONFLICT, "Delivery address has no pincode."
        )
    return await available_for_pincode(session, merchant_id, slip.address_pincode)


async def available_for_pincode(
    session: AsyncSession, merchant_id: str, pincode: str
) -> list[AvailableVehicleResponse]:
    """Return active merchant vehicles explicitly mapped to a destination pincode."""
    rows = (
        await session.execute(
            select(Vehicle, VehiclePincodeMapping)
            .join(VehiclePincodeMapping, VehiclePincodeMapping.vehicle_id == Vehicle.id)
            .where(
                Vehicle.merchant_id == merchant_id,
                Vehicle.is_active.is_(True),
                VehiclePincodeMapping.merchant_id == merchant_id,
                VehiclePincodeMapping.pincode == pincode,
                VehiclePincodeMapping.is_active.is_(True),
            )
            .order_by(VehiclePincodeMapping.priority, Vehicle.number)
        )
    ).all()
    return [
        AvailableVehicleResponse(
            id=vehicle.id,
            number=vehicle.number,
            label=vehicle.label,
            notes=vehicle.notes,
            is_active=vehicle.is_active,
            created_at=vehicle.created_at,
            priority=mapping.priority,
            matched_pincode=mapping.pincode,
        )
        for vehicle, mapping in rows
    ]
