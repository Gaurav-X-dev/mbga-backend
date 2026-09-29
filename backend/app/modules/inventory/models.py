"""Warehouse tables: the live counts, and the ledger that explains every one of them.

Two tables, and the relationship between them is the module's whole integrity story:

* `stock_items` holds the **current** count per cylinder type. It is what the app reads, and
  it exists so the warehouse screen is one indexed row per type rather than a sum over the
  ledger's whole history.
* `stock_movements` is an **append-only ledger**. Every count change writes one row saying
  what moved, by how much, who recorded it and what it was against.

Neither is the source of truth on its own: the counts are what the app shows and the ledger is
what proves them, and spec §18.6 requires that they always agree. Nothing anywhere updates a
count without writing a movement in the same transaction - that is enforced in
`ledger.py`, which is the only code that writes either table.

Movements are never updated or deleted. A count entered wrongly is fixed by a `CORRECTION`
movement that records the old and new figures, so the trail shows the mistake and its repair
rather than silently rewriting history. That is also why `deltas` are stored signed and
per-bucket instead of being recomputed: a movement has to still read correctly years later,
after thresholds and labels have moved on.

Ids are opaque UUIDs with no readable counterpart, unlike orders. Nobody quotes a stock
movement id - staff refer to the challan or vehicle number, which is what `reference_id`
holds - so a per-merchant sequence would add a lock on the busiest write in the module (every
dispatched line writes a movement) to produce a string no one reads.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

#: Microsecond precision, because the order of the ledger *is* its meaning. Plain MySQL
#: DATETIME keeps whole seconds, so three movements recorded while someone works through a
#: delivery all land on the same instant and come back in an arbitrary order - the history
#: screen would show a refill after the dispatch it paid for. Declared as a variant so the
#: column is DATETIME(6) on MySQL and MariaDB and a plain timestamp anywhere else.
LEDGER_TIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


class StockItem(Base):
    """One cylinder type's live counts for one merchant.

    A row is created the first time that merchant records any movement for the type. Absence
    means "never stocked", which the snapshot renders as zeros - and deliberately raises no
    alert, because a cylinder a godown does not carry is not a cylinder it has run out of.
    """

    __tablename__ = "stock_items"
    __table_args__ = (
        # One row per type per merchant. This is also the lock target on every movement, so
        # two staff recording stock for the same cylinder serialise on it and neither
        # update is lost.
        UniqueConstraint("merchant_id", "cylinder_type", name="uq_stock_items_merchant_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    cylinder_type: Mapped[str] = mapped_column(String(40))

    # Never negative. Enforced in `ledger.py` rather than by a CHECK constraint, so the
    # refusal reaches the app as the coded 409 the spec asks for ("Not enough filled 19 KG
    # in stock") instead of a database error the client cannot read.
    filled: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    empty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    damaged: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # When `filled` drops below this, the snapshot raises an alert and the bell gets a
    # notification. Seeded from `DEFAULT_REORDER_THRESHOLDS`; no endpoint changes it (§11).
    reorder_threshold: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Bumped by every movement, and returned as `updatedAt` so the app can show how stale a
    # count is. A warehouse figure nobody has touched since Tuesday is worth knowing about.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockMovement(Base):
    """One entry in the ledger. Append-only: written once, never updated.

    `quantity` is always positive - it is the size of the movement, the thing a person would
    say out loud ("sixty came in"). The direction lives in the signed `delta_*` columns,
    because one movement can touch two buckets at once: marking two empties damaged is
    `empty -2, damaged +2`, a single event that moves cylinders sideways rather than in or out.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        # The history screen: this merchant, newest first, optionally filtered by cylinder.
        Index("ix_stock_movements_merchant_recorded", "merchant_id", "recorded_at"),
        Index("ix_stock_movements_merchant_type_recorded", "merchant_id", "cylinder_type", "recorded_at"),
        # Reconciling a delivery or a challan back to the counts it moved.
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(30))
    cylinder_type: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)

    # Signed, per bucket, and zero where a bucket was untouched. Stored rather than derived
    # from `movement_type` so the row still explains itself if the rules for a type change.
    delta_filled: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delta_empty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    delta_damaged: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Which bucket the staff member named (`fromBucket` / `bucket`). Kept for the audit trail:
    # the deltas say what happened, this says what was asked for.
    bucket: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # A correction's before-and-after. Null on every other type. Without these a correction
    # reads as "filled -3" with no way to tell whether the count was 240 or 24.
    previous_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # A challan number, a vehicle number or a delivery slip id. Free text, because a BPCL
    # challan is whatever BPCL printed on it.
    reference_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Denormalised display name, resolved from the session at write time and never from the
    # request body. Kept on the row so the ledger still says who recorded a movement after
    # that person has left and their account is gone.
    recorded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recorded_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(LEDGER_TIME)
