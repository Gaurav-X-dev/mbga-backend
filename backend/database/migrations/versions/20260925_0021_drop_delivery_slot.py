"""Drop the delivery slot, make the delivery date a date, and retire the PREPARING status.

Three related changes, all of them the same decision: the platform promises a **delivery day** and
nothing finer.

1. `orders.delivery_slot` is dropped. It held "09:00 AM – 01:00 PM" or "02:00 PM – 06:00 PM",
   derived from which side of the 16:00 cut-off an order landed. The godown never scheduled
   against it, so it was a promise that got broken.

2. `orders.scheduled_delivery_date` becomes a `DATE`. It was a timestamp holding 09:00 or 14:00
   IST as a UTC instant, which only existed to carry the slot's start time. A delivery day has no
   time of day, and storing one is what made the field renderable five and a half hours out.

3. Orders sitting in `PREPARING` are moved to `CONFIRMED`. The status is gone from the catalogue,
   and a row left in it would render as an unknown chip on both apps and could never be moved
   again - `STATUS_TRANSITIONS` has no entry for it. `CONFIRMED` is the honest landing place: the
   cylinders had not left the godown.

`delivery_slips.scheduled_date` becomes a `DATE` for the same reason - a van goes out on a day.

**Not reversible without loss.** The downgrade restores the columns and their types, but the slot
values themselves are gone and the time-of-day on both dates comes back as midnight. That is
stated rather than hidden: these columns held a promise the business stopped making.

Revision ID: 20260925_0021
Revises: 20260925_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0021"
down_revision = "20260925_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Before the column changes: a row in a status that no longer exists cannot be moved by any
    # endpoint, because the transition table has no entry for it.
    op.execute(sa.text("UPDATE orders SET status = 'CONFIRMED' WHERE status = 'PREPARING'"))
    # The trail keeps its PREPARING rows on purpose. They are history - those orders really did
    # pass through that step - and rewriting an append-only audit log to match a schema change is
    # how a trail stops being evidence.

    op.drop_column("orders", "delivery_slot")
    # MySQL casts DATETIME to DATE in place, keeping the day and dropping the time.
    op.alter_column(
        "orders",
        "scheduled_delivery_date",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        existing_nullable=False,
    )
    op.alter_column(
        "delivery_slips",
        "scheduled_date",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "delivery_slips",
        "scheduled_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    op.alter_column(
        "orders",
        "scheduled_delivery_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
    )
    # Restored empty: the slot text is not recoverable, and inventing one would be worse than a
    # null that says plainly that nothing is known.
    op.add_column("orders", sa.Column("delivery_slot", sa.String(40), nullable=True))
