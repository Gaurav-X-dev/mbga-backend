from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class DeliveryProfile(Base):
    __tablename__ = "delivery_profiles"
    __table_args__ = (
        Index("ix_delivery_profiles_merchant_status", "merchant_id", "status"),
        UniqueConstraint("merchant_id", "employee_code", name="uq_delivery_profiles_merchant_employee_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    delivery_user_type: Mapped[str] = mapped_column(String(30), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    driving_license_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    driving_license_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    approval_status: Mapped[str] = mapped_column(String(30), index=True)
    vehicle_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    on_duty: Mapped[bool] = mapped_column(default=False)
    language_code: Mapped[str | None] = mapped_column(String(10), default="en", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
