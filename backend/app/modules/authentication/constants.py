from enum import StrEnum


class LoginChannel(StrEnum):
    CUSTOMER = "CUSTOMER"
    DELIVERY = "DELIVERY"
    MERCHANT = "MERCHANT"
    ADMIN = "ADMIN"


class TokenType(StrEnum):
    BEARER = "Bearer"


class SessionType(StrEnum):
    """Value of the access token's `token_type` claim and of `login_sessions.session_type`."""

    ACCESS = "access"
    # Restricted customer-registration session: valid only on /customer/registration routes.
    ONBOARDING = "onboarding"


REFRESH_TOKEN_TYPE = "refresh"


class UserStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class AuthEventType(StrEnum):
    """Audit event types (audit_logs.event_type) for authentication."""

    OTP_REQUESTED = "auth.otp_requested"
    OTP_RESEND_REQUESTED = "auth.otp_resend_requested"
    OTP_REQUEST_REJECTED = "auth.otp_request_rejected"
    OTP_VERIFICATION_SUCCEEDED = "auth.otp_verification_succeeded"
    OTP_VERIFICATION_FAILED = "auth.otp_verification_failed"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_REJECTED = "auth.login_rejected"
    TOKEN_REFRESHED = "auth.token_refreshed"
    TOKEN_REFRESH_REJECTED = "auth.token_refresh_rejected"
    REFRESH_TOKEN_REUSE_DETECTED = "auth.refresh_token_reuse_detected"
    LOGOUT = "auth.logout"
    LOGOUT_ALL = "auth.logout_all"
    SESSION_REVOKED = "auth.session_revoked"
    BLOCKED_ACCOUNT_ACCESS = "auth.blocked_account_access"


# Numeric channel codes accepted from mobile clients in place of the string names.
# The wire/storage format stays the string value; these are an input convenience only.
CHANNEL_CODES: dict[int, LoginChannel] = {
    1: LoginChannel.CUSTOMER,
    2: LoginChannel.DELIVERY,
    3: LoginChannel.MERCHANT,
    4: LoginChannel.ADMIN,
}
