"""Order and OrderItem models for the order management domain."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.database.base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_merchant_status", "merchant_id", "status"),
        Index("ix_orders_customer_profile", "customer_profile_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    customer_profile_id: Mapped[str] = mapped_column(
        ForeignKey("customer_profiles.id"), index=True
    )
    customer_name: Mapped[str] = mapped_column(String(160))
    customer_phone: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(String(500))
    address_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_slot_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    time_slot_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True, default="pending")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Relationships
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="order", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))  # cylinderDelivery | emptyCollection
    label: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer)

    # Relationships
    order: Mapped[Order] = relationship("Order", back_populates="items")
