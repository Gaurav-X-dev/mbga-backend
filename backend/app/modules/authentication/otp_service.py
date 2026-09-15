import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.app import Settings
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.authentication.password_hasher import hash_secret
from app.modules.authentication.schemas import OTPRequest


class OTPService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def generate_otp(self) -> str:
        upper_bound = 10 ** self.settings.otp_length
        return f"{secrets.randbelow(upper_bound):0{self.settings.otp_length}d}"

    async def store_hashed_otp(
        self,
        *,
        payload: OTPRequest,
        mobile_number: str,
        purpose: str,
        login_channel: LoginChannel,
        otp: str,
        ip_address: str | None = None,
    ) -> OtpChallenge:
        now = datetime.now(UTC)
        challenge = OtpChallenge(
            id=str(uuid4()),
            mobile_number=mobile_number,
            purpose=purpose,
            login_channel=login_channel.value,
            otp_hash=hash_secret(otp),
            attempts=0,
            max_attempts=self.settings.otp_max_attempts,
            device_id=payload.device.device_id if payload.device else None,
            device_type=payload.device.device_type if payload.device else None,
            app_version=payload.device.app_version if payload.device else None,
            ip_address=ip_address,
            created_at=now,
            expires_at=now + timedelta(seconds=self.settings.otp_expiry_seconds),
            resend_available_at=now + timedelta(seconds=self.settings.otp_resend_cooldown_seconds),
            consumed_at=None,
        )
        self.session.add(challenge)
        await self.session.flush()
        return challenge
