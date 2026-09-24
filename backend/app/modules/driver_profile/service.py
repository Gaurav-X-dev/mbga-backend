"""Service for Driver Profile and status management (API Reference §8)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.models import Delivery
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.driver_profile.schemas import (
    DriverProfileResponse,
    UpdateLanguageResponse,
)
from app.modules.users.models import User

SUPPORTED_LANGUAGES = {"en", "hi", "mr", "gu", "ta", "te", "kn", "bn", "pa"}


def compute_avatar_initials(name: str | None) -> str | None:
    if not name:
        return None
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return None


class DriverProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_profile(self, user_id: str) -> DriverProfileResponse:
        user = await self.session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DRIVER_NOT_FOUND", "message": "Driver account not found."},
            )

        delivery_profile = await self.session.scalar(
            select(DeliveryProfile).where(DeliveryProfile.user_id == user_id)
        )

        name = user.full_name or user.username or "Driver"
        phone = user.mobile_number or ""
        vehicle_number = delivery_profile.vehicle_number if delivery_profile else None
        on_duty = delivery_profile.on_duty if delivery_profile else False

        return DriverProfileResponse(
            id=user.id,
            name=name,
            phone=phone,
            vehicleNumber=vehicle_number,
            role="Driver",
            onDuty=on_duty,
            avatarInitials=compute_avatar_initials(name),
        )

    async def update_status(self, user_id: str, on_duty: bool) -> DriverProfileResponse:
        if not on_duty:
            # Check if active in_progress delivery exists
            active = await self.session.scalar(
                select(Delivery).where(
                    Delivery.driver_user_id == user_id,
                    Delivery.status == "in_progress",
                )
            )
            if active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "CONFLICT",
                        "message": "Cannot go off duty with an active delivery in progress.",
                    },
                )

        delivery_profile = await self.session.scalar(
            select(DeliveryProfile).where(DeliveryProfile.user_id == user_id)
        )
        if delivery_profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "DRIVER_NOT_FOUND", "message": "Driver profile not found."},
            )
        delivery_profile.on_duty = on_duty
        delivery_profile.updated_at = datetime.now(UTC)

        await self.session.commit()
        return await self.get_profile(user_id)

    async def update_language(self, user_id: str, language_code: str) -> UpdateLanguageResponse:
        code = language_code.strip().lower()
        if code not in SUPPORTED_LANGUAGES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "VALIDATION_ERROR",
                    "message": f"languageCode '{code}' is not supported.",
                },
            )

        delivery_profile = await self.session.scalar(
            select(DeliveryProfile).where(DeliveryProfile.user_id == user_id)
        )
        if delivery_profile:
            delivery_profile.language_code = code
            delivery_profile.updated_at = datetime.now(UTC)
            await self.session.commit()

        return UpdateLanguageResponse(languageCode=code)
