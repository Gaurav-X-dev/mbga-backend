from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.schemas import (
    CurrentUserResponse,
    LogoutRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPResendRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    TokenPair,
)
from app.modules.authentication.service import AuthenticationService

router = APIRouter()


@router.post("/otp/request", response_model=OTPRequestResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_otp(
    payload: OTPRequest,
    service: Annotated[AuthenticationService, Depends(get_authentication_service)],
) -> OTPRequestResponse:
    return await service.request_otp(payload)


@router.post("/otp/verify", response_model=OTPVerifyResponse)
async def verify_otp(payload: OTPVerifyRequest) -> OTPVerifyResponse:
    # TODO: Validate OTP, role/channel, user status, session, tokens, and audit event.
    raise NotImplementedError


@router.post("/otp/resend", response_model=OTPRequestResponse, status_code=status.HTTP_202_ACCEPTED)
async def resend_otp(payload: OTPResendRequest) -> OTPRequestResponse:
    # TODO: Enforce resend cooldown and issue a new hashed OTP.
    raise NotImplementedError


@router.post("/token/refresh", response_model=TokenPair)
async def refresh_token(payload: RefreshTokenRequest) -> TokenPair:
    # TODO: Validate refresh token, rotate token, and revoke old token.
    raise NotImplementedError


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest) -> None:
    # TODO: Revoke the current device/session refresh token.
    return None


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(payload: LogoutRequest) -> None:
    # TODO: Revoke all sessions for the authenticated user.
    return None


@router.get("/me", response_model=CurrentUserResponse)
async def me() -> CurrentUserResponse:
    # TODO: Resolve current user from access token.
    raise NotImplementedError
