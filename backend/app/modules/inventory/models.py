"""Driver-inventory model — §10 of the API Reference."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class DriverInventory(Base):
    __tablename__ = "driver_inventory"
    __table_args__ = (
        Index("ix_driver_inventory_driver_user_id", "driver_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    driver_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id"), unique=True, index=True
    )
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    full_cylinder_count: Mapped[int] = mapped_column(Integer, default=0)
    empty_cylinder_count: Mapped[int] = mapped_column(Integer, default=0)
    vehicle_capacity: Mapped[int] = mapped_column(Integer, default=30)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
