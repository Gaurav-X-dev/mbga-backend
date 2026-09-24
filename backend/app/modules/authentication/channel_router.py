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
    OTPResendRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    TokenPair,
)
from app.modules.authentication.service import AuthenticationService, session_types_for_purpose
from app.shared.exceptions.openapi import error_responses

bearer_scheme = HTTPBearer(auto_error=False)


def build_channel_auth_router(channel: LoginChannel, purpose: str, prefix: str = "/auth") -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[f"{channel.value.lower()}-auth"])
    session_types = session_types_for_purpose(purpose)

    @router.post(
        "/otp/request",
        response_model=OTPRequestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses=error_responses(403, 404, 422, 429),
    )
    async def request_otp(
        payload: OTPRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPRequestResponse:
        payload.login_channel = channel
        return await service.request_otp(payload, purpose=purpose, channel=channel)

    @router.post(
        "/otp/resend",
        response_model=OTPRequestResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses=error_responses(400, 403, 404, 422, 429),
    )
    async def resend_otp(
        payload: OTPResendRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPRequestResponse:
        return await service.resend_otp(payload, purpose=purpose, channel=channel)

    @router.post("/otp/verify", response_model=OTPVerifyResponse, responses=error_responses(400, 403, 404, 422))
    async def verify_otp(
        payload: OTPVerifyRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> OTPVerifyResponse:
        return await service.verify_otp(payload, purpose=purpose, channel=channel)

    @router.post("/token/refresh", response_model=TokenPair, responses=error_responses(401, 403, 422))
    async def refresh_token(
        payload: RefreshTokenRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> TokenPair:
        return await service.refresh_token(payload, channel=channel, session_types=session_types)

    @router.post(
        "/logout",
        status_code=status.HTTP_204_NO_CONTENT,
        responses=error_responses(422),
        description="Revokes the session of the given refresh token. Always returns 204, even when nothing was revoked.",
    )
    async def logout(
        payload: LogoutRequest,
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> None:
        await service.logout(payload, channel=channel)

    @router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(401, 403))
    async def logout_all(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> None:
        await service.logout_all(credentials.credentials if credentials else None, channel=channel, session_types=session_types)

    @router.get("/me", response_model=CurrentUserResponse, responses=error_responses(401, 403))
    async def me(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        service: Annotated[AuthenticationService, Depends(get_authentication_service)],
    ) -> CurrentUserResponse:
        return await service.me(credentials.credentials if credentials else None, channel=channel, session_types=session_types)

    return router
