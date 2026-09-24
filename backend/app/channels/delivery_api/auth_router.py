"""Authentication routes for Delivery App (API Reference §5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.schemas import (
    LogoutRequest,
    OTPRequest,
    OTPVerifyRequest,
    RefreshTokenRequest,
)
from app.modules.authentication.service import AuthenticationService
from app.modules.driver_profile.service import DriverProfileService
from app.modules.users.models import User
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import success_response

bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/auth", tags=["delivery-auth"])


class LoginRequest(BaseModel):
    phone: str = Field(description="Driver registered phone number")


class VerifyOtpRequest(BaseModel):
    phone: str
    otp: str
    otpToken: str


class RefreshRequest(BaseModel):
    refreshToken: str


@router.post("/login", operation_id="delivery_auth_login")
async def login(
    payload: LoginRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """POST /auth/login — §5.1: Request driver login OTP."""
    phone_clean = payload.phone.strip()
    if not phone_clean:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "A valid phone number is required.",
            },
        )

    try:
        normalized = normalize_mobile_number(phone_clean)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "A valid phone number is required.",
            },
        ) from exc

    # Check if driver user exists
    user = await session.scalar(select(User).where(User.mobile_number == normalized))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "DRIVER_NOT_FOUND",
                "message": "No driver account found for this phone number.",
            },
        )

    try:
        otp_req = OTPRequest(
            mobile_number=normalized,
            login_channel=LoginChannel.DELIVERY,
        )
        challenge_resp = await service.request_otp(
            otp_req,
            purpose="DELIVERY_LOGIN",
            channel=LoginChannel.DELIVERY,
        )
    except HTTPException as e:
        raise e
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(exc),
            },
        ) from exc

    return success_response({
        "otpToken": challenge_resp.request_id,
        "expiresInSeconds": challenge_resp.expires_in,
    })


@router.post("/verify-otp", operation_id="delivery_auth_verify_otp")
async def verify_otp(
    payload: VerifyOtpRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    """POST /auth/verify-otp — §5.2: Verify OTP and return tokens + driver profile."""
    if not payload.otp or len(payload.otp) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "Enter the 6-digit code."},
        )

    try:
        verify_req = OTPVerifyRequest(
            request_id=payload.otpToken,
            otp=payload.otp,
        )
        resp = await service.verify_otp(
            verify_req,
            purpose="DELIVERY_LOGIN",
            channel=LoginChannel.DELIVERY,
        )
    except HTTPException as exc:
        # Re-map error detail into the expected error code
        code = "OTP_INVALID"
        msg = "Incorrect or expired code. Request a new one."
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", code)
            msg = exc.detail.get("message", msg)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": code, "message": msg},
        ) from exc

    driver_profile_service = DriverProfileService(session)
    driver_data = await driver_profile_service.get_profile(resp.user_id)

    return success_response({
        "accessToken": resp.token.access_token,
        "refreshToken": resp.token.refresh_token,
        "driver": driver_data.model_dump(by_alias=True, exclude_none=True),
    })


@router.post("/refresh", operation_id="delivery_auth_refresh")
async def refresh_token(
    payload: RefreshRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
):
    """POST /auth/refresh — §5.3: Silent refresh of access/refresh token pair."""
    try:
        req = RefreshTokenRequest(refresh_token=payload.refreshToken)
        token_pair = await service.refresh_token(req, channel=LoginChannel.DELIVERY)
        return success_response({
            "accessToken": token_pair.access_token,
            "refreshToken": token_pair.refresh_token,
        })
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": "Session expired. Please log in again.",
            },
        ) from exc


@router.post("/logout", operation_id="delivery_auth_logout")
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
):
    """POST /auth/logout — §5.4: Invalidate current driver session."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Session already expired."},
        )
    try:
        me = await service.me(credentials.credentials, channel=LoginChannel.DELIVERY)
        await service.logout_all(me.user_id)
    except Exception:
        # Client treats any response as success or 401
        pass

    return success_response(None)
