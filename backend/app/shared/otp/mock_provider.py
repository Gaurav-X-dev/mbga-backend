import logging

from app.shared.otp.provider import OTPDeliveryProvider, OTPDeliveryResult, mask_for_log

logger = logging.getLogger(__name__)


class MockOTPProvider(OTPDeliveryProvider):
    """Local and test environments only: nothing is sent. Use DEV_FIXED_OTP_CODE to sign in locally."""

    async def send_otp(self, *, mobile_number: str, otp: str, purpose: str, expires_in_seconds: int) -> OTPDeliveryResult:
        # Never log the code.
        logger.info("Mock OTP delivery for %s (%s)", mask_for_log(mobile_number), purpose)
        return OTPDeliveryResult(provider="mock")
