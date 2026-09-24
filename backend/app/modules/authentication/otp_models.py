from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        Index("ix_otp_challenges_mobile_purpose_channel", "mobile_number", "purpose", "login_channel"),
        Index("ix_otp_challenges_expires_at", "expires_at"),
        Index("ix_otp_challenges_ip_created", "ip_address", "created_at"),
        Index("ix_otp_challenges_mobile_created", "mobile_number", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mobile_number: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    login_channel: Mapped[str] = mapped_column(String(30), index=True)
    otp_hash: Mapped[str] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True when the number has no eligible account: the request looks accepted but nothing is sent
    # and the challenge can never be verified.
    dispatch_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # SENT, SUPPRESSED; provider message reference when the provider returns one.
    delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
