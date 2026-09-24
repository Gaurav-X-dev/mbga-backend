"""Service layer for delivery lifecycle execution."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.models import Delivery
from app.modules.deliveries.repository import DeliveryRepository
from app.modules.deliveries.schemas import (
    ConfirmDeliveryRequest,
    ConfirmDeliveryResponse,
    DeliveryResponse,
    StartDeliveryResponse,
    VerifyCustomerOtpResponse,
)
from app.modules.inventory.models import DriverInventory
from app.modules.notifications.models import Notification
from app.modules.orders.models import Order
from app.modules.orders.schemas import OrderItemResponse
from app.shared.otp.provider import OTPDeliveryProvider
from app.shared.utils.geo import haversine_distance_meters


def delivery_to_response(delivery: Delivery) -> DeliveryResponse:
    order: Order | None = delivery.order
    if order is None:
        return DeliveryResponse(
            id=delivery.id,
            orderNumber=delivery.id,
            customerName="Unknown Customer",
            customerPhone="",
            address="",
            status=delivery.status,
            distanceKm=None,
            completedAt=None,
            items=[],
        )

    completed_at_str: str | None = None
    if delivery.completed_at or order.completed_at:
        ts = delivery.completed_at or order.completed_at
        completed_at_str = ts.strftime("%I:%M %p") if ts else None

    items = [
        OrderItemResponse(
            id=item.id,
            kind=item.kind,
            label=item.label,
            quantity=item.quantity,
        )
        for item in (order.items or [])
    ]

    return DeliveryResponse(
        id=delivery.id,
        orderNumber=order.order_number,
        customerName=order.customer_name,
        customerPhone=order.customer_phone,
        address=order.address,
        timeSlotStart=order.time_slot_start,
        timeSlotEnd=order.time_slot_end,
        status=delivery.status,
        distanceKm=order.distance_km,
        completedAt=completed_at_str,
        items=items,
    )


class DeliveryService:
    def __init__(
        self,
        repository: DeliveryRepository,
        session: AsyncSession,
        otp_provider: OTPDeliveryProvider,
    ) -> None:
        self.repository = repository
        self.session = session
        self.otp_provider = otp_provider

    async def get_today_deliveries(self, driver_user_id: str) -> list[dict]:
        deliveries = await self.repository.list_today_deliveries(driver_user_id)
        return [delivery_to_response(d).model_dump(by_alias=True) for d in deliveries]

    async def get_delivery_by_id(self, delivery_id: str, driver_user_id: str) -> DeliveryResponse:
        delivery = await self.repository.get_by_id_for_driver(delivery_id, driver_user_id)
        if delivery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Delivery not found."},
            )
        return delivery_to_response(delivery)

    async def start_delivery(
        self,
        delivery_id: str,
        driver_user_id: str,
        latitude: float,
        longitude: float,
    ) -> StartDeliveryResponse:
        delivery = await self.repository.get_by_id_for_driver(delivery_id, driver_user_id)
        if delivery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Delivery not found."},
            )

        order = delivery.order
        distance_meters: float = 42.0  # default inside geofence if coordinates not set on order
        if order and order.address_latitude is not None and order.address_longitude is not None:
            distance_meters = round(
                haversine_distance_meters(
                    latitude,
                    longitude,
                    order.address_latitude,
                    order.address_longitude,
                ),
                1,
            )

        is_at_location = distance_meters <= 200.0

        now = datetime.now(UTC)
        delivery.driver_latitude = latitude
        delivery.driver_longitude = longitude
        delivery.distance_meters_from_destination = distance_meters
        delivery.status = "in_progress"
        delivery.started_at = now
        delivery.updated_at = now

        if order:
            order.status = "in_progress"
            order.updated_at = now

        await self.session.commit()

        return StartDeliveryResponse(
            isAtLocation=is_at_location,
            distanceMetersFromDestination=distance_meters,
        )

    async def confirm_delivery(
        self,
        delivery_id: str,
        driver_user_id: str,
        request: ConfirmDeliveryRequest,
    ) -> ConfirmDeliveryResponse:
        delivery = await self.repository.get_by_id_for_driver(delivery_id, driver_user_id)
        if delivery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Delivery not found."},
            )

        order = delivery.order
        if order and order.items:
            cylinder_quantity = sum(item.quantity for item in order.items if item.kind == "cylinderDelivery")
            empty_quantity = sum(item.quantity for item in order.items if item.kind == "emptyCollection")
            if request.deliveredQuantity > cylinder_quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "VALIDATION_ERROR",
                        "message": "deliveredQuantity cannot exceed the ordered quantity.",
                    },
                )
            if request.emptyCollectedQuantity > empty_quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "VALIDATION_ERROR",
                        "message": "emptyCollectedQuantity cannot exceed the ordered quantity.",
                    },
                )

        # Generate 6-digit OTP for customer verification
        otp = str(secrets.randbelow(900000) + 100000)
        otp_hash = hashlib.sha256(otp.encode()).hexdigest()

        now = datetime.now(UTC)
        delivery.delivered_quantity = request.deliveredQuantity
        delivery.empty_collected_quantity = request.emptyCollectedQuantity
        delivery.notes = request.notes
        delivery.customer_otp_hash = otp_hash
        delivery.customer_otp_expires_at = now + timedelta(minutes=15)
        delivery.confirmed_at = now
        delivery.updated_at = now

        if order:
            await self.otp_provider.send_otp(
                mobile_number=order.customer_phone,
                country_code="+91",
                message=f"Your MBGA delivery confirmation OTP is {otp}.",
            )
        await self.session.commit()

        return ConfirmDeliveryResponse(
            deliveryId=delivery.id,
            customerOtpRequired=True,
        )

    async def verify_customer_otp(
        self,
        delivery_id: str,
        driver_user_id: str,
        otp: str,
    ) -> VerifyCustomerOtpResponse:
        delivery = await self.repository.get_by_id_for_driver(delivery_id, driver_user_id)
        if delivery is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Delivery not found."},
            )

        now = datetime.now(UTC)

        # Check OTP validity
        otp_hash = hashlib.sha256(otp.strip().encode()).hexdigest()
        is_valid = False

        expires_at = delivery.customer_otp_expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if (
            delivery.customer_otp_hash
            and delivery.customer_otp_hash == otp_hash
            and expires_at
            and expires_at >= now
        ):
            is_valid = True

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "OTP_INVALID",
                    "message": "Incorrect code. Ask the customer to confirm again.",
                },
            )

        # Complete delivery and order
        delivery.status = "completed"
        delivery.completed_at = now
        delivery.updated_at = now

        order = delivery.order
        order_number = order.order_number if order else delivery.id
        if order:
            order.status = "completed"
            order.completed_at = now
            order.updated_at = now

        # Update driver inventory
        delivered_qty = delivery.delivered_quantity or 0
        empty_qty = delivery.empty_collected_quantity or 0

        inventory = await self.session.scalar(
            select(DriverInventory).where(DriverInventory.driver_user_id == driver_user_id)
        )
        if inventory:
            inventory.full_cylinder_count = max(0, inventory.full_cylinder_count - delivered_qty)
            inventory.empty_cylinder_count += empty_qty
            inventory.last_updated_at = now

        # Create confirmation notification
        notification = Notification(
            id=f"notif-{uuid4().hex[:8]}",
            user_id=driver_user_id,
            type="delivery_confirmed",
            title="Delivery Confirmed",
            subtitle=f"#{order_number}",
            is_read=False,
            created_at=now,
        )
        self.session.add(notification)

        await self.session.commit()

        return VerifyCustomerOtpResponse(
            deliveryId=delivery.id,
            orderNumber=order_number,
            deliveredQuantity=delivered_qty,
            emptyCollectedQuantity=empty_qty,
            completedAt=now.isoformat(),
        )
