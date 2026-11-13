"""Trip plans and custody; delivery slips remain the source of fulfillment facts."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class LogisticsSettings(Base):
    __tablename__ = "logistics_settings"
    scope: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Trip(Base):
    __tablename__ = "delivery_trips"
    __table_args__ = (
        UniqueConstraint("merchant_id", "idempotency_key", name="uq_trip_request"),
        UniqueConstraint("merchant_id", "number", name="uq_trip_number"),
    )
    number: Mapped[str] = mapped_column(String(40))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    vehicle_number: Mapped[str] = mapped_column(String(50), index=True)
    driver_user_id: Mapped[str] = mapped_column(String(36), index=True)
    driver_name: Mapped[str] = mapped_column(String(160))
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(Text)
    route_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_submission: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_odometer: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_odometer: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    return_submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TripStop(Base):
    __tablename__ = "delivery_trip_stops"
    __table_args__ = (UniqueConstraint("trip_id", "sequence", name="uq_trip_sequence"),)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("delivery_slips.id"), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("delivery_trips.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    pinned: Mapped[bool] = mapped_column(default=False)


class TripLoadLine(Base):
    __tablename__ = "delivery_trip_loads"
    __table_args__ = (
        Index("ix_trip_custody_active", "merchant_id", "active", "cylinder_type"),
        CheckConstraint(
            "loaded_filled >= 0 AND opening_empty >= 0 AND remaining_filled >= 0 AND current_empty >= 0",
            name="trip_load_nonnegative",
        ),
    )
    trip_id: Mapped[str] = mapped_column(ForeignKey("delivery_trips.id"), primary_key=True)
    cylinder_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    active: Mapped[bool] = mapped_column(default=True)
    remaining_filled: Mapped[int] = mapped_column(BigInteger)
    current_empty: Mapped[int] = mapped_column(BigInteger)
    loaded_filled: Mapped[int] = mapped_column(BigInteger)
    opening_empty: Mapped[int] = mapped_column(BigInteger, default=0)
