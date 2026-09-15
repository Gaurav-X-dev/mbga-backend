from app.shared.otp.provider import OTPDeliveryProvider


class SMSOTPProvider(OTPDeliveryProvider):
    async def send_otp(self, *, mobile_number: str, country_code: str, message: str) -> None:
        # TODO: Integrate selected SMS vendor after MBGA confirms provider and credentials.
        raise NotImplementedError("Real SMS provider is not configured yet.")
