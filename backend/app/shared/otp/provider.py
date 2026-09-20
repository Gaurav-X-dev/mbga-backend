from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OTPDeliveryResult:
    provider: str
    reference: str | None = None


class OTPDeliveryError(Exception):
    """The code could not be delivered. The reason must never contain the code or the full number."""

    def __init__(self, reason: str, *, retryable: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


class OTPDeliveryProvider(ABC):
    @abstractmethod
    async def send_otp(self, *, mobile_number: str, otp: str, purpose: str, expires_in_seconds: int) -> OTPDeliveryResult:
        """Deliver `otp` to `mobile_number` (+91XXXXXXXXXX). Raise OTPDeliveryError on failure."""
        raise NotImplementedError


def mask_for_log(mobile_number: str) -> str:
    return f"******{mobile_number[-4:]}" if len(mobile_number) >= 4 else "******"
