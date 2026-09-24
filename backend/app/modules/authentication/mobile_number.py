import re

INDIA_COUNTRY_CODES = {"+91", "91"}
INVALID_MOBILE_MESSAGE = "Enter a valid 10-digit Indian mobile number."

# Indian mobile numbers are 10 digits and start with 6, 7, 8 or 9.
_NATIONAL_MOBILE = re.compile(r"^[6-9]\d{9}$")


class InvalidMobileNumberError(ValueError):
    """Raised for mobile numbers that are not valid Indian mobile numbers.

    Subclasses ValueError so existing `except ValueError` handlers keep working;
    unhandled occurrences are converted to a 422 response by the app exception handler.
    """


def normalize_mobile_number(mobile_number: str) -> str:
    if re.search(r"[A-Za-z]", mobile_number):
        raise InvalidMobileNumberError("Mobile number must not contain letters")
    digits = re.sub(r"\D", "", mobile_number)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 10 and _NATIONAL_MOBILE.match(digits):
        return f"+91{digits}"
    raise InvalidMobileNumberError("Invalid Indian mobile number")


def ensure_india_country_code(country_code: str | None) -> None:
    if country_code is not None and country_code.strip() not in INDIA_COUNTRY_CODES:
        raise InvalidMobileNumberError("Only Indian (+91) mobile numbers are supported")
