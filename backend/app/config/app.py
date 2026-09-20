from functools import lru_cache
from typing import Any

from pydantic import AnyUrl, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_ENVIRONMENTS = {"local", "development", "dev", "test"}
MIN_SIGNING_SECRET_BYTES = 32
WEAK_SIGNING_SECRETS = {"", "secret", "changeme", "change-me", "change-me-local-only", "jwt-secret", "your-secret-key"}


class Settings(BaseSettings):
    # hide_input_in_errors: a rejected value (for example a weak secret) is never printed in startup errors.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)

    app_name: str = "MBGA Backend"
    app_version: str = "0.1.0"
    app_env: str = "local"
    debug: bool = False
    api_prefix: str = "/api/v1"
    # Swagger UI and OpenAPI JSON. Unset = enabled only in local/development/test.
    api_docs_enabled_override: bool | None = Field(default=None, validation_alias="API_DOCS_ENABLED")
    allowed_cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    # Reverse proxies whose X-Forwarded-For header is trusted (IP addresses or CIDR ranges).
    trusted_proxy_ips: list[str] = Field(default_factory=list)

    database_url: str = "mysql+asyncmy://mbga_user:change_me@mysql:3306/mbga?charset=utf8mb4"
    redis_url: str = "redis://redis:6379/0"
    # Redis only backs the permission cache; permission checks always fall back to the database.
    # REDIS_ENABLED=false is accepted only in local/development/test environments.
    redis_enabled: bool = True
    redis_socket_connect_timeout_seconds: float = Field(default=0.5, gt=0, le=10)
    redis_socket_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    redis_failure_backoff_seconds: float = Field(default=30.0, ge=0, le=3600)

    jwt_algorithm: str = "HS256"
    jwt_signing_secret: str = "change-me-local-only"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 30
    # A refresh token replayed within this window after its rotation (e.g. two parallel refresh calls
    # from one app) is refused without revoking the whole sign-in. Later replays revoke the family.
    refresh_reuse_grace_seconds: int = Field(default=10, ge=0, le=60)

    otp_length: int = Field(default=6, ge=4, le=8)
    otp_expires_seconds: int = 300
    otp_expiry_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_requests_per_hour: int = 5
    # Deprecated and unused; the delivery provider is chosen with SMS_PROVIDER.
    otp_provider: str = "development"
    dev_fixed_otp_enabled: bool = False
    dev_fixed_otp_code: str | None = None
    # Returns the plaintext code in the OTP request/resend response so app developers can test
    # sign-in before SMS auto-read is wired up. Refused outside local/development/test.
    dev_expose_otp_in_response: bool = False
    otp_request_limit_per_mobile: int = 5
    # Hourly limits shared by all app instances (stored in auth_throttle_events).
    otp_request_limit_per_ip: int = Field(default=20, ge=1)
    otp_request_limit_per_device: int = Field(default=10, ge=1)
    otp_verify_limit_per_ip: int = Field(default=60, ge=1)
    check_mobile_limit_per_ip: int = Field(default=30, ge=1)
    # Wrong codes per number per hour, across all codes, before new codes are refused.
    otp_max_failed_attempts_per_hour: int = Field(default=10, ge=1)
    auth_audit_store_ip: bool = True
    permission_cache_ttl_seconds: int = 300

    # "mock" (local/development/test only) or "sms" (requires the SMS_API_* settings).
    sms_provider: str = "mock"
    sms_api_base_url: AnyUrl | None = None
    sms_api_key: str | None = None
    sms_sender_id: str | None = None
    sms_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    sms_max_retries: int = Field(default=2, ge=0, le=5)
    rbac_bootstrap_super_admin_enabled: bool = False
    rbac_bootstrap_super_admin_user_id: str | None = None
    rbac_bootstrap_super_admin_email: str | None = None
    rbac_bootstrap_super_admin_username: str | None = None
    rbac_bootstrap_super_admin_full_name: str = "Super Admin"
    rbac_bootstrap_super_admin_mobile_number: str | None = None
    rbac_bootstrap_super_admin_country_code: str = "+91"

    @computed_field
    @property
    def is_local_environment(self) -> bool:
        return self.app_env.lower() in LOCAL_ENVIRONMENTS

    @computed_field
    @property
    def api_docs_enabled(self) -> bool:
        if self.api_docs_enabled_override is not None:
            return self.api_docs_enabled_override
        return self.is_local_environment

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

    @field_validator("redis_enabled", mode="after")
    @classmethod
    def reject_disabled_redis_outside_local(cls, value: bool, info) -> bool:
        env = str(info.data.get("app_env", "local")).lower()
        if not value and env not in LOCAL_ENVIRONMENTS:
            raise ValueError("REDIS_ENABLED=false is allowed only in local/development/test")
        return value

    @field_validator("debug", mode="after")
    @classmethod
    def reject_debug_outside_local(cls, value: bool, info) -> bool:
        env = str(info.data.get("app_env", "local")).lower()
        if value and env not in LOCAL_ENVIRONMENTS:
            raise ValueError("DEBUG=true is allowed only in local/development/test")
        return value

    @field_validator("jwt_signing_secret", mode="after")
    @classmethod
    def reject_weak_signing_secret(cls, value: str, info) -> str:
        env = str(info.data.get("app_env", "local")).lower()
        if env in LOCAL_ENVIRONMENTS:
            return value
        # The value itself is never included in the error message.
        if value.strip().lower() in WEAK_SIGNING_SECRETS or any(marker in value.lower() for marker in ("change-me", "change_me", "changeme", "placeholder")):
            raise ValueError("JWT_SIGNING_SECRET uses a placeholder value; generate a random secret")
        if len(value.encode("utf-8")) < MIN_SIGNING_SECRET_BYTES or len(set(value)) < 16:
            raise ValueError(f"JWT_SIGNING_SECRET must be a random value of at least {MIN_SIGNING_SECRET_BYTES} bytes")
        return value

    @field_validator("sms_provider", mode="after")
    @classmethod
    def validate_sms_provider(cls, value: str, info) -> str:
        value = value.strip().lower()
        if value not in {"mock", "sms"}:
            raise ValueError("SMS_PROVIDER must be 'mock' or 'sms'")
        env = str(info.data.get("app_env", "local")).lower()
        if value == "mock" and env not in LOCAL_ENVIRONMENTS:
            raise ValueError("SMS_PROVIDER=mock is allowed only in local/development/test")
        return value

    @field_validator("dev_fixed_otp_code", mode="after")
    @classmethod
    def validate_fixed_code_format(cls, value: str | None, info) -> str | None:
        length = info.data.get("otp_length", 6)
        if info.data.get("dev_fixed_otp_enabled") and (value is None or not value.isdigit() or len(value) != length):
            raise ValueError("DEV_FIXED_OTP_CODE must be a numeric code of OTP_LENGTH digits")
        return value

    @field_validator("dev_fixed_otp_enabled", mode="after")
    @classmethod
    def reject_fixed_otp_outside_local(cls, value: bool, info) -> bool:
        env = str(info.data.get("app_env", "local")).lower()
        if value and env not in LOCAL_ENVIRONMENTS:
            raise ValueError("DEV_FIXED_OTP_ENABLED is allowed only in local/development/test")
        return value

    @field_validator("dev_expose_otp_in_response", mode="after")
    @classmethod
    def reject_exposed_otp_outside_local(cls, value: bool, info) -> bool:
        # Returning the code makes the OTP step worthless: anyone who can call the endpoint can sign
        # in as any account. The app must never boot with this on outside a throwaway environment.
        env = str(info.data.get("app_env", "local")).lower()
        if value and env not in LOCAL_ENVIRONMENTS:
            raise ValueError("DEV_EXPOSE_OTP_IN_RESPONSE is allowed only in local/development/test")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
