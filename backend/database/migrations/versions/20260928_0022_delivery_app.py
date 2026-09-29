"""Give the delivery app the columns it needs. Nothing is moved, nothing is dropped.

Three additive changes, all nullable or defaulted, so this runs against a live database without
a backfill and without a window.

1. `delivery_profiles` gains `vehicle_number` and `on_duty`. On duty is the driver's own switch
   rather than the office's - it is how they signal the end of a shift - and the vehicle is the
   van they run, defaulted onto a slip raised for them.

2. `customer_delivery_sites` gains `latitude` and `longitude`. Used only to tell a driver how
   far they still are from the gate. They are expected to stay null for most sites - nobody
   surveys a customer's godown to onboard them - so every read treats a missing coordinate as
   "cannot measure", never as "wrong place".

3. `delivery_slips` gains `started_at`, `driver_latitude` and `driver_longitude`: when the
   driver pressed Start, and where they were. Deliberately separate from `dispatched_at`, which
   is the office marking the van loaded. The two are routinely an hour apart, and only the new
   one is evidence of where the driver actually stood.

No new tables. The delivery app reads the same `delivery_slips` the dispatch board writes -
one slip, one truth - rather than a parallel `deliveries` table that would have to be kept in
step with it.

Reversible in full: the downgrade drops exactly what the upgrade added.

Revision ID: 20260928_0022
Revises: 20260925_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0022"
down_revision = "20260925_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- the driver's own settings ----------------------------------------------------------
    op.add_column("delivery_profiles", sa.Column("vehicle_number", sa.String(length=50), nullable=True))
    # server_default so existing rows land off duty rather than NULL: a driver the office has
    # never seen on the app is not on duty, and NOT NULL keeps every later read total.
    op.add_column(
        "delivery_profiles",
        sa.Column("on_duty", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    # The driver's list is "my slips, by status". Without this it is a scan of every slip the
    # merchant has ever raised, on the one screen that opens on every shift.
    op.create_index(
        "ix_delivery_profiles_user_duty", "delivery_profiles", ["user_id", "on_duty"]
    )

    # --- where the van is going --------------------------------------------------------------
    op.add_column("customer_delivery_sites", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("customer_delivery_sites", sa.Column("longitude", sa.Float(), nullable=True))

    # --- what the driver recorded when they set off -------------------------------------------
    op.add_column("delivery_slips", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("delivery_slips", sa.Column("driver_latitude", sa.Float(), nullable=True))
    op.add_column("delivery_slips", sa.Column("driver_longitude", sa.Float(), nullable=True))
    # Copied off the site when the slip is raised, so the driver's distance needs no join
    # and still reads correctly after the site is edited.
    op.add_column("delivery_slips", sa.Column("destination_latitude", sa.Float(), nullable=True))
    op.add_column("delivery_slips", sa.Column("destination_longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("delivery_slips", "destination_longitude")
    op.drop_column("delivery_slips", "destination_latitude")
    op.drop_column("delivery_slips", "driver_longitude")
    op.drop_column("delivery_slips", "driver_latitude")
    op.drop_column("delivery_slips", "started_at")

    op.drop_column("customer_delivery_sites", "longitude")
    op.drop_column("customer_delivery_sites", "latitude")

    op.drop_index("ix_delivery_profiles_user_duty", table_name="delivery_profiles")
    op.drop_column("delivery_profiles", "on_duty")
    op.drop_column("delivery_profiles", "vehicle_number")
