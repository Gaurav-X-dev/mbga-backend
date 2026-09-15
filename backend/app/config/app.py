from functools import lru_cache

from typing import Any

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MBGA Backend"
    app_version: str = "0.1.0"
    app_env: str = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"
    allowed_cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    trusted_proxy_ips: list[str] = Field(default_factory=list)

    database_url: str = "mysql+asyncmy://mbga_user:change_me@mysql:3306/mbga?charset=utf8mb4"
    redis_url: str = "redis://redis:6379/0"

    jwt_algorithm: str = "HS256"
    jwt_signing_secret: str = "change-me-local-only"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 30

    otp_length: int = 6
    otp_expires_seconds: int = 300
    otp_expiry_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_requests_per_hour: int = 5
    otp_provider: str = "development"
    dev_fixed_otp_enabled: bool = False
    dev_fixed_otp_code: str | None = None
    otp_request_limit_per_mobile: int = 5
    otp_request_limit_per_ip: int = 20
    permission_cache_ttl_seconds: int = 300

    sms_provider: str = "mock"
    sms_api_base_url: AnyUrl | None = None
    sms_api_key: str | None = None
    sms_sender_id: str | None = None
    rbac_bootstrap_super_admin_enabled: bool = False
    rbac_bootstrap_super_admin_user_id: str | None = None
    rbac_bootstrap_super_admin_email: str | None = None
    rbac_bootstrap_super_admin_username: str | None = None
    rbac_bootstrap_super_admin_full_name: str = "Super Admin"
    rbac_bootstrap_super_admin_mobile_number: str | None = None
    rbac_bootstrap_super_admin_country_code: str = "+91"

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: Any) -> Any:
        if isinstance(value, str) and value.lower() in {"release", "prod", "production"}:
            return False
        return value

    @field_validator("sms_api_base_url", mode="before")
    @classmethod
    def parse_optional_url(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("dev_fixed_otp_enabled", mode="after")
    @classmethod
    def reject_fixed_otp_outside_local(cls, value: bool, info) -> bool:
        env = str(info.data.get("app_env", "local")).lower()
        if value and env not in {"local", "development", "dev", "test"}:
            raise ValueError("DEV_FIXED_OTP_ENABLED is allowed only in local/development/test")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
