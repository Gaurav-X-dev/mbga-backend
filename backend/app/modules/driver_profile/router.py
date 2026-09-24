"""FastAPI router for Driver Profile domain (API Reference §8)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.driver_profile.schemas import (
    UpdateLanguageRequest,
    UpdateStatusRequest,
)
from app.modules.driver_profile.service import DriverProfileService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import success_response

router = APIRouter(tags=["delivery-driver-profile"])


def get_driver_profile_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DriverProfileService:
    return DriverProfileService(session)


@router.get("/driver/profile")
async def get_driver_profile(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DriverProfileService, Depends(get_driver_profile_service)],
):
    """GET /driver/profile — §8.1: Driver profile."""
    profile = await service.get_profile(auth.user_id)
    return success_response(profile.model_dump(by_alias=True, exclude_none=True))


@router.patch("/driver/status")
async def update_driver_status(
    payload: UpdateStatusRequest,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DriverProfileService, Depends(get_driver_profile_service)],
):
    """PATCH /driver/status — §8.2: Toggle on/off duty."""
    profile = await service.update_status(auth.user_id, on_duty=payload.onDuty)
    return success_response(profile.model_dump(by_alias=True, exclude_none=True))


@router.patch("/driver/language")
async def update_driver_language(
    payload: UpdateLanguageRequest,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DriverProfileService, Depends(get_driver_profile_service)],
):
    """PATCH /driver/language — §8.3: Change language preference."""
    result = await service.update_language(auth.user_id, language_code=payload.languageCode)
    return success_response(result.model_dump(by_alias=True))
