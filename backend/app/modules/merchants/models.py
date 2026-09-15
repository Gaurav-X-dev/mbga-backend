from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class Merchant(Base):
    __tablename__ = "merchants"
    __table_args__ = (
        Index("ix_merchants_status_code", "status", "code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    mobile_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    approval_status: Mapped[str] = mapped_column(String(30), index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MerchantUser(Base):
    __tablename__ = "merchant_users"
    __table_args__ = (
        UniqueConstraint("merchant_id", "user_id", name="uq_merchant_user"),
        Index("ix_merchant_users_merchant_status", "merchant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    staff_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
