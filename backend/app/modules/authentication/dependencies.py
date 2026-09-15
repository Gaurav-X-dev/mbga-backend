from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings, get_settings
from app.modules.authentication.otp_service import OTPService
from app.modules.authentication.repository import AuthenticationRepository
from app.modules.authentication.service import AuthenticationService
from app.shared.database.session import get_db_session
from app.shared.otp.mock_provider import MockOTPProvider
from app.shared.otp.provider import OTPDeliveryProvider


def get_otp_provider(settings: Annotated[Settings, Depends(get_settings)]) -> OTPDeliveryProvider:
    # TODO: Return real SMS provider when configured and reviewed.
    return MockOTPProvider()


def get_authentication_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[OTPDeliveryProvider, Depends(get_otp_provider)],
) -> AuthenticationService:
    repository = AuthenticationRepository(session)
    otp_service = OTPService(session, settings)
    return AuthenticationService(repository, otp_service, provider, settings)
