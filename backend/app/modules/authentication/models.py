from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class LoginSession(Base):
    __tablename__ = "login_sessions"
    __table_args__ = (
        Index("ix_login_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_login_sessions_family_id", "family_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(255))
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # NULL on sessions created before 20260917_0008; the token claims are used for those.
    login_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    session_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # All sessions created by rotating one sign-in share a family; NULL = the session is its own family.
    family_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Push (FCM) token of the device holding this session; cleared when the session is revoked.
    push_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthThrottleEvent(Base):
    """One counted request per bucket and hashed key (client IP, device or mobile number)."""

    __tablename__ = "auth_throttle_events"
    __table_args__ = (
        Index("ix_auth_throttle_bucket_key_created", "bucket", "key_hash", "created_at"),
        Index("ix_auth_throttle_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bucket: Mapped[str] = mapped_column(String(40))
    key_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
