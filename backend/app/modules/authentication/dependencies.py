from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.audit import ClientInfo
from app.modules.authentication.otp_service import OTPService
from app.modules.authentication.repository import AuthenticationRepository
from app.modules.authentication.service import AuthenticationService
from app.shared.database.session import get_db_session
from app.shared.middleware.client_ip import client_ip
from app.shared.otp.hanuotp_provider import HanuOTPProvider
from app.shared.otp.mock_provider import MockOTPProvider
from app.shared.otp.provider import OTPDeliveryProvider
from app.shared.otp.sms_provider import SMSOTPProvider


def get_otp_provider(settings: Annotated[Settings, Depends(get_settings)]) -> OTPDeliveryProvider:
    """The single delivery provider, shared by every login channel.

    Customer, Customer registration, Merchant, Delivery and Admin all resolve the same object
    through this one dependency, so a provider change reaches every channel at once.
    """
    # Settings validation guarantees the mock provider is never selected outside local/development/test.
    if settings.sms_provider == "hanuotp":
        return HanuOTPProvider(settings)
    if settings.sms_provider == "sms":
        return SMSOTPProvider(settings)
    return MockOTPProvider()


def get_client_info(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> ClientInfo:
    return ClientInfo(
        ip_address=client_ip(request, settings.trusted_proxy_ips),
        user_agent=request.headers.get("user-agent"),
    )


def get_authentication_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[OTPDeliveryProvider, Depends(get_otp_provider)],
    client: Annotated[ClientInfo, Depends(get_client_info)],
) -> AuthenticationService:
    repository = AuthenticationRepository(session)
    otp_service = OTPService(session, settings)
    return AuthenticationService(repository, otp_service, provider, settings, client)
