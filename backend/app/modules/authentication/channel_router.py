from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.dependencies import get_authentication_service
from app.modules.authentication.schemas import (
    CurrentUserResponse,
    LogoutRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    TokenPair,
)
from app.modules.authentication.service import AuthenticationService

bearer_scheme = HTTPBearer(auto_error=False)


def build_channel_auth_router(channel: LoginChannel, purpose: str, prefix: str = "/auth") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[f"{channel.value.lower()}-auth"])

    @router.post("/otp/request", response_model=OTPRequestResponse, status_code=status.HTTP_202_ACCEPTED)
    async def request_otp(
        payload: OTPRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPRequestResponse:
        payload.login_channel = channel
        return await service.request_otp(payload, purpose=purpose, channel=channel)

    @router.post("/otp/resend", response_model=OTPRequestResponse, status_code=status.HTTP_202_ACCEPTED)
    async def resend_otp(
        payload: OTPRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPRequestResponse:
        payload.login_channel = channel
        return await service.request_otp(payload, purpose=purpose, channel=channel)

    @router.post("/otp/verify", response_model=OTPVerifyResponse)
    async def verify_otp(
        payload: OTPVerifyRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPVerifyResponse:
        return await service.verify_otp(payload, purpose=purpose, channel=channel)

    @router.post("/token/refresh", response_model=TokenPair)
    async def refresh_token(
        payload: RefreshTokenRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> TokenPair:
        return await service.refresh_token(payload, channel=channel)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        payload: LogoutRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> None:
        await service.logout(payload)

    @router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
    async def logout_all(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> None:
        me = await service.me(credentials.credentials if credentials else "", channel=channel)
        await service.logout_all(me.user_id)

    @router.get("/me", response_model=CurrentUserResponse)
    async def me(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> CurrentUserResponse:
        return await service.me(credentials.credentials if credentials else "", channel=channel)

    return router
