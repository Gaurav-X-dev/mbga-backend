from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
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

    # --- what the delivery app owns -------------------------------------------------------
    # The van this driver runs. Shown on their profile screen and defaulted onto a slip raised
    # for them; nullable because a merchant may assign a vehicle per trip rather than per driver.
    vehicle_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # On duty means "assignable right now". It is the driver's own switch, not the office's -
    # going off duty is how they signal the end of a shift, and it is refused while a van of
    # theirs is still out, because the cylinders on it are nobody else's to deliver.
    on_duty: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Latest accepted GPS ping. Nullable fields keep older app versions fully compatible.
    current_latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    current_longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    location_accuracy: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DriverLocationLog(Base):
    """One immutable breadcrumb received while a driver was on duty."""

    __tablename__ = "driver_location_logs"
    __table_args__ = (
        Index("ix_driver_location_logs_driver_recorded", "driver_id", "recorded_at"),
        Index("ix_driver_location_logs_merchant_recorded", "merchant_id", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    driver_id: Mapped[str] = mapped_column(ForeignKey("delivery_profiles.id"), nullable=False)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    longitude: Mapped[float] = mapped_column(Numeric(10, 7), nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
