"""FastAPI router for Deliveries domain (API Reference §6 & §7)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.dependencies import get_otp_provider
from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.deliveries.repository import DeliveryRepository
from app.modules.deliveries.schemas import (
    ConfirmDeliveryRequest,
    StartDeliveryRequest,
    VerifyCustomerOtpRequest,
)
from app.modules.deliveries.service import DeliveryService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import success_response
from app.shared.otp.provider import OTPDeliveryProvider

router = APIRouter(tags=["delivery-deliveries"])


def get_delivery_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    otp_provider: Annotated[OTPDeliveryProvider, Depends(get_otp_provider)],
) -> DeliveryService:
    return DeliveryService(DeliveryRepository(session), session, otp_provider)


@router.get("/deliveries/today")
async def get_today_deliveries(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    """GET /deliveries/today — §6.1: Today's assigned deliveries."""
    data = await service.get_today_deliveries(driver_user_id=auth.user_id)
    return success_response(data)


@router.get("/deliveries/{delivery_id}")
async def get_delivery_by_id(
    delivery_id: str,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    """GET /deliveries/{deliveryId} — §6.2 alias: Order/Delivery detail."""
    delivery = await service.get_delivery_by_id(
        delivery_id=delivery_id, driver_user_id=auth.user_id
    )
    return success_response(delivery.model_dump(by_alias=True))


@router.post("/deliveries/{delivery_id}/start")
async def start_delivery(
    delivery_id: str,
    payload: StartDeliveryRequest,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    """POST /deliveries/{deliveryId}/start — §7.1: Driver starts delivery."""
    result = await service.start_delivery(
        delivery_id=delivery_id,
        driver_user_id=auth.user_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    return success_response(result.model_dump(by_alias=True))


@router.post("/deliveries/{delivery_id}/confirm")
async def confirm_delivery(
    delivery_id: str,
    payload: ConfirmDeliveryRequest,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    """POST /deliveries/{deliveryId}/confirm — §7.2: Confirm delivery quantities."""
    result = await service.confirm_delivery(
        delivery_id=delivery_id,
        driver_user_id=auth.user_id,
        request=payload,
    )
    return success_response(result.model_dump(by_alias=True))


@router.post("/deliveries/{delivery_id}/verify-customer-otp")
async def verify_customer_otp(
    delivery_id: str,
    payload: VerifyCustomerOtpRequest,
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[DeliveryService, Depends(get_delivery_service)],
):
    """POST /deliveries/{deliveryId}/verify-customer-otp — §7.3: Customer verification OTP."""
    result = await service.verify_customer_otp(
        delivery_id=delivery_id,
        driver_user_id=auth.user_id,
        otp=payload.otp,
    )
    return success_response(result.model_dump(by_alias=True))
