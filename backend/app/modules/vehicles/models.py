"""The vans a merchant delivers with.

Until now a vehicle was a string typed into the assignment form. Nothing held the list, so every
assignment was a fresh chance to mistype a plate - and a typo did not fail, it quietly created a
second van. `MP09 GH 4521` and `MP09GH4521` were two vehicles as far as the slips were
concerned, and the rule that stops one person being sent out on two vans could not see that they
were the same one.

**A vehicle is not a driver's.** Any driver may take any van on any day, which is how a round is
actually run: whoever is on shift takes whatever is loaded. There is deliberately no owning
driver on this row, and no default - tying the two together would be a rule the godown breaks
every week.

**Deactivated, never deleted.** A van that is sold or off the road stops being offered, but
every slip it ever carried still names it, and those slips have to keep reading.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class Vehicle(Base):
    """One van, owned by one merchant."""

    __tablename__ = "vehicles"
    __table_args__ = (
        # The plate is the identity. Two rows for one van would let the double-booking rule
        # pass a driver who is already out in it.
        UniqueConstraint("merchant_id", "number", name="uq_vehicles_merchant_number"),
        Index("ix_vehicles_merchant_active", "merchant_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)

    #: Upper-cased and single-spaced, as `check_vehicle_number` normalises it. Stored that way
    #: so the unique key catches `mp09gh4521` as the van it already is.
    number: Mapped[str] = mapped_column(String(50))
    #: What the office calls it - "Tata 407", "the small one". Optional; the plate is the name
    #: that matters, and a label nobody fills in is better absent than blank.
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    #: Off the road, sold, or simply retired. Soft, because the slips it carried still name it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VehiclePincodeMapping(Base):
    """A merchant-controlled delivery area for one vehicle."""

    __tablename__ = "vehicle_pincode_mappings"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "pincode", name="uq_vehicle_pincode_mapping"),
        Index("ix_vehicle_pincode_merchant_pin", "merchant_id", "pincode", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), index=True)
    pincode: Mapped[str] = mapped_column(String(6))
    priority: Mapped[int] = mapped_column(default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
