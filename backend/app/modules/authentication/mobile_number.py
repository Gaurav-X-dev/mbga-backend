import re


def normalize_mobile_number(mobile_number: str) -> str:
    if re.search(r"[A-Za-z]", mobile_number):
        raise ValueError("Mobile number must not contain letters")
    digits = re.sub(r"\D", "", mobile_number)
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    raise ValueError("Invalid Indian mobile number")
