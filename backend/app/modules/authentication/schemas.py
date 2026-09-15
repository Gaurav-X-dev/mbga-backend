from pydantic import BaseModel, Field

from app.modules.authentication.constants import LoginChannel, TokenType
from app.shared.authorization.roles import UserRole


class DeviceInfo(BaseModel):
    device_id: str | None = None
    device_type: str | None = None
    device_name: str | None = None
    app_version: str | None = None
    fcm_token: str | None = None


class OTPRequest(BaseModel):
    mobile_number: str = Field(min_length=6, max_length=15)
    country_code: str = Field(default="+91", min_length=1, max_length=5)
    login_channel: LoginChannel = LoginChannel.CUSTOMER
    device: DeviceInfo | None = None


class OTPRequestResponse(BaseModel):
    request_id: str
    message: str = "OTP request accepted"
    expires_in: int
    resend_after: int
    code: str = "OTP_REQUEST_ACCEPTED"


class OTPVerifyRequest(BaseModel):
    request_id: str
    mobile_number: str | None = Field(default=None, min_length=6, max_length=15)
    country_code: str = Field(default="+91", min_length=1, max_length=5)
    login_channel: LoginChannel = LoginChannel.CUSTOMER
    otp: str = Field(pattern=r"^[0-9]{4}$")
    device: DeviceInfo | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: TokenType = TokenType.BEARER
    expires_in: int


class OTPVerifyResponse(BaseModel):
    token: TokenPair | None = None
    user_id: str | None = None
    role: UserRole | None = None
    login_channel: LoginChannel | None = None
    is_new_user: bool = False
    code: str = "OTP_VERIFIED"
    message: str = "OTP verified"


class OTPResendRequest(BaseModel):
    request_id: str
    mobile_number: str = Field(min_length=6, max_length=15)
    country_code: str = Field(default="+91", min_length=1, max_length=5)
    login_channel: LoginChannel = LoginChannel.CUSTOMER


class RefreshTokenRequest(BaseModel):
    refresh_token: str
    device_id: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    device_id: str | None = None


class CurrentUserResponse(BaseModel):
    user_id: str
    display_name: str | None = None
    mobile_number: str | None = None
    country_code: str | None = None
    role: UserRole | None = None
    active_roles: list[str] = Field(default_factory=list)
    effective_permissions: list[str] = Field(default_factory=list)
    login_channel: LoginChannel | None = None
    status: str
    merchant: dict | None = None
    profile: dict | None = None
