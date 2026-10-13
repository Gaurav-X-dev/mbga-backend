"""States and the cities in them, for the address forms.

The states were a tuple in the seeder - six names written into the source, with no cities at
all - so the city box was free text and "Gurgaon", "Gurugram" and "gurugram " were three places
in the reports. A delivery area is business data: it changes when the agency opens a route, not
when the backend ships.

**Served, not yet enforced.** The forms read their options from here; a typed value that is not
in the table is still accepted. Enforcing it would reject every customer already on the books
outside the seeded state, and there is one seeded state today. The check that *is* applied is
narrower and cannot misfire: a city claimed under a state the table does know must be a city of
that state.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class State(Base):
    """One state the agency delivers in."""

    __tablename__ = "states"
    __table_args__ = (UniqueConstraint("code", name="uq_states_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: The short form the apps send back - "HR". Stable; the name may be reworded, this is not.
    code: Mapped[str] = mapped_column(String(10))
    #: What a person reads and what an address stores - "Haryana".
    name: Mapped[str] = mapped_column(String(120), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class City(Base):
    """One city, under exactly one state."""

    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("state_id", "slug", name="uq_cities_state_slug"),
        Index("ix_cities_state_active", "state_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_id: Mapped[str] = mapped_column(ForeignKey("states.id"), index=True)
    #: The stable identity, set once from the seeded name and never changed - "gurugram".
    #: `name` is what people read and may reword; without something underneath it, a renamed
    #: city stops matching and the seeder puts the old name back beside the new one.
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostalLocation(Base):
    """One post-office row from the authoritative pincode directory."""

    __tablename__ = "postal_locations"
    __table_args__ = (
        UniqueConstraint("pincode", "office_name", name="uq_postal_locations_pincode_office"),
        Index("ix_postal_locations_pincode_active", "pincode", "is_active"),
        Index("ix_postal_locations_state_district", "state_name", "district_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pincode: Mapped[str] = mapped_column(String(6))
    office_name: Mapped[str] = mapped_column(String(160))
    office_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivery_available: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    district_name: Mapped[str] = mapped_column(String(120))
    state_name: Mapped[str] = mapped_column(String(120))
    circle_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    division_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
