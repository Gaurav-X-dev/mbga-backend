"""Delivery model for the delivery execution domain."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.orders.models import Order
from app.shared.database.base import Base


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_driver_status", "driver_user_id", "status"),
        Index("ix_deliveries_driver_date", "driver_user_id", "created_at"),
        Index("ix_deliveries_order_id", "order_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    driver_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(30), index=True, default="pending"
    )  # pending | in_progress | completed

    # Quantities recorded at confirmation (§7.2)
    delivered_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    empty_collected_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Driver location captured at start (§7.1)
    driver_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    driver_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_meters_from_destination: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # Customer OTP for delivery verification (§7.3)
    customer_otp_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_otp_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship("Order", lazy="selectin")
