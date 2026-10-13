"""Give the vans and the delivery area a table each.

**Vehicles.** A vehicle was a string typed into the assignment form. Nothing held the list, so
every assignment was a chance to mistype a plate, and a typo did not fail - it quietly created a
second van. `MP09 GH 4521` and `MP09GH4521` were two vehicles as far as the slips were
concerned, and the rule that stops one person being sent out on two vans could not see they were
the same one.

Every distinct number already on a slip is carried into the new table, per merchant, so no
assignment that works today stops working: the catalogue starts out holding exactly the vans
the agency has been using. Numbers are normalised the way `check_vehicle_number` normalises
them - upper-cased and single-spaced - which is what lets the unique key collapse the typos.

**States and cities.** The states were a tuple of six names in the seeder and the city box was
free text, so "Gurgaon", "Gurugram" and "gurugram " were three places in the reports. A delivery
area is business data: it changes when the agency opens a route, not when the backend ships.
Rows are seeded separately, so this migration only makes the space.

Nothing here is enforced on existing addresses. A customer whose state is not in the table keeps
their address exactly as it reads.

Revision ID: 20261008_0033
Revises: 20261008_0032
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0033"
down_revision = "20261008_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("number", sa.String(50), nullable=False),
        sa.Column("label", sa.String(80), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "number", name="uq_vehicles_merchant_number"),
    )
    op.create_index("ix_vehicles_merchant_id", "vehicles", ["merchant_id"])
    op.create_index("ix_vehicles_merchant_active", "vehicles", ["merchant_id", "is_active"])

    op.create_table(
        "states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_states_code"),
    )
    op.create_index("ix_states_name", "states", ["name"])

    op.create_table(
        "cities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_id", sa.String(36), sa.ForeignKey("states.id"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("state_id", "slug", name="uq_cities_state_slug"),
    )
    op.create_index("ix_cities_state_id", "cities", ["state_id"])
    op.create_index("ix_cities_slug", "cities", ["slug"])
    op.create_index("ix_cities_name", "cities", ["name"])
    op.create_index("ix_cities_state_active", "cities", ["state_id", "is_active"])

    # Every van already in use becomes a row, so the catalogue starts out complete and no
    # assignment that works today starts failing. UUID() per row; the normalisation mirrors
    # `check_vehicle_number` - upper case, and runs of whitespace collapsed to one space.
    op.execute(
        sa.text(
            """
            INSERT INTO vehicles (id, merchant_id, number, is_active, created_at, updated_at)
            SELECT UUID(), s.merchant_id,
                   UPPER(TRIM(REGEXP_REPLACE(s.vehicle_number, '[[:space:]]+', ' '))),
                   1, UTC_TIMESTAMP(), UTC_TIMESTAMP()
              FROM delivery_slips s
             WHERE s.vehicle_number IS NOT NULL
               AND TRIM(s.vehicle_number) <> ''
             GROUP BY s.merchant_id,
                      UPPER(TRIM(REGEXP_REPLACE(s.vehicle_number, '[[:space:]]+', ' ')))
            """
        )
    )


def downgrade() -> None:
    op.drop_table("cities")
    op.drop_table("states")
    op.drop_table("vehicles")
