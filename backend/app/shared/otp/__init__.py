"""OTP delivery providers.

One provider serves every login channel. It is selected by `SMS_PROVIDER` and resolved in
`app.modules.authentication.dependencies.get_otp_provider`.
"""

from app.shared.otp.hanuotp_provider import HanuOTPProvider
from app.shared.otp.mock_provider import MockOTPProvider
from app.shared.otp.provider import (
    OTPDeliveryError,
    OTPDeliveryProvider,
    OTPDeliveryResult,
    mask_for_log,
)
from app.shared.otp.sms_provider import SMSOTPProvider

__all__ = [
    "HanuOTPProvider",
    "MockOTPProvider",
    "OTPDeliveryError",
    "OTPDeliveryProvider",
    "OTPDeliveryResult",
    "SMSOTPProvider",
    "mask_for_log",
]
