import logging

from app.shared.otp.provider import OTPDeliveryProvider

logger = logging.getLogger(__name__)


class MockOTPProvider(OTPDeliveryProvider):
    async def send_otp(self, *, mobile_number: str, country_code: str, message: str) -> None:
        logger.info("Mock OTP send requested for %s%s: %s", country_code, mobile_number, message)
