from abc import ABC, abstractmethod


class OTPDeliveryProvider(ABC):
    @abstractmethod
    async def send_otp(self, *, mobile_number: str, country_code: str, message: str) -> None:
        raise NotImplementedError
