from enum import StrEnum


class LoginChannel(StrEnum):
    CUSTOMER = "CUSTOMER"
    DELIVERY = "DELIVERY"
    MERCHANT = "MERCHANT"
    ADMIN = "ADMIN"


class TokenType(StrEnum):
    BEARER = "Bearer"


class UserStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class AuthEventType(StrEnum):
    OTP_REQUESTED = "OTP_REQUESTED"
    OTP_VERIFIED = "OTP_VERIFIED"
    TOKEN_REFRESHED = "TOKEN_REFRESHED"
    LOGOUT = "LOGOUT"
    LOGOUT_ALL = "LOGOUT_ALL"
