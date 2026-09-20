"""Configurable SMS provider for staging and production.

No SMS vendor has been selected, so `_dispatch` is not implemented: every send fails with a clear,
non-retryable error and the API answers 503 OTP_DELIVERY_FAILED.
Status: BLOCKED BY SMS VENDOR CONFIGURATION.

To integrate a vendor, implement `_dispatch` (one HTTP call that returns the vendor message ID) and map
vendor errors to OTPDeliveryError(retryable=...). Never log the code or the full number.
"""

import asyncio
import logging

from app.config.app import Settings
from app.shared.otp.provider import (
    OTPDeliveryError,
    OTPDeliveryProvider,
    OTPDeliveryResult,
    mask_for_log,
)

logger = logging.getLogger(__name__)


class SMSOTPProvider(OTPDeliveryProvider):
    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("SMS_API_BASE_URL", settings.sms_api_base_url),
                ("SMS_API_KEY", settings.sms_api_key),
                ("SMS_SENDER_ID", settings.sms_sender_id),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"SMS provider is not configured: missing {', '.join(missing)}")
        self.base_url = str(settings.sms_api_base_url)
        self.api_key = settings.sms_api_key
        self.sender_id = settings.sms_sender_id
        self.timeout_seconds = settings.sms_timeout_seconds
        self.max_retries = settings.sms_max_retries

    async def send_otp(self, *, mobile_number: str, otp: str, purpose: str, expires_in_seconds: int) -> OTPDeliveryResult:
        attempt = 0
        while True:
            attempt += 1
            try:
                reference = await asyncio.wait_for(
                    self._dispatch(mobile_number=mobile_number, otp=otp, purpose=purpose, expires_in_seconds=expires_in_seconds),
                    timeout=self.timeout_seconds,
                )
                return OTPDeliveryResult(provider="sms", reference=reference)
            except TimeoutError:
                error = OTPDeliveryError("SMS_TIMEOUT", retryable=True)
            except OTPDeliveryError as exc:
                error = exc
            logger.warning("SMS delivery to %s failed (%s, attempt %s)", mask_for_log(mobile_number), error.reason, attempt)
            if not error.retryable or attempt > self.max_retries:
                raise error
            await asyncio.sleep(min(0.25 * attempt, 1.0))

    async def _dispatch(self, *, mobile_number: str, otp: str, purpose: str, expires_in_seconds: int) -> str | None:
        raise OTPDeliveryError("SMS_VENDOR_NOT_INTEGRATED")
