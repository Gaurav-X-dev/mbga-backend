"""Fixed credentials apply only to three named review accounts and their login channels."""

from app.modules.authentication.constants import LoginChannel


def review_numbers(settings):
    if not settings.play_review_otp_enabled:
        return {}
    return {
        LoginChannel.CUSTOMER: settings.play_review_customer_mobile,
        LoginChannel.MERCHANT: settings.play_review_merchant_mobile,
        LoginChannel.DELIVERY: settings.play_review_delivery_mobile,
    }


def review_code_for(settings, mobile, purpose, channel):
    numbers = review_numbers(settings)
    if (
        mobile
        and channel in numbers
        and numbers[channel] == mobile
        and purpose == f"{channel.value}_LOGIN"
    ):
        return settings.play_review_otp_code
    return None
