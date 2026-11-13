"""Customer priorities, trip plans and audited vehicle custody; no historical returns inferred."""

from datetime import UTC, datetime
import sqlalchemy as sa
from alembic import op

revision = "20261104_0072"
down_revision = "20261103_0071"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer_profiles", sa.Column("priority_code", sa.String(30), nullable=True))
    op.create_index("ix_customer_profiles_priority_code", "customer_profiles", ["priority_code"])
    op.add_column(
        "orders", sa.Column("priority_code", sa.String(30), nullable=True, server_default="MEDIUM")
    )
    op.create_index("ix_orders_priority_code", "orders", ["priority_code"])
    op.execute(sa.text("UPDATE orders SET priority_code = 'MEDIUM' WHERE priority_code IS NULL"))
    op.create_table(
        "logistics_settings",
        sa.Column("scope", sa.String(36), primary_key=True, nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "delivery_trips",
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("vehicle_number", sa.String(50), nullable=False),
        sa.Column("driver_user_id", sa.String(36), nullable=False),
        sa.Column("driver_name", sa.String(160), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("route_preview", sa.Text(), nullable=True),
        sa.Column("return_submission", sa.Text(), nullable=True),
        sa.Column("verification", sa.Text(), nullable=True),
        sa.Column("start_odometer", sa.BigInteger(), nullable=True),
        sa.Column("end_odometer", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("return_submitted_by", sa.String(36), nullable=True),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("merchant_id", "idempotency_key", name="uq_trip_request"),
        sa.UniqueConstraint("merchant_id", "number", name="uq_trip_number"),
    )
    op.create_index("ix_delivery_trips_driver_user_id", "delivery_trips", ["driver_user_id"])
    op.create_index("ix_delivery_trips_merchant_id", "delivery_trips", ["merchant_id"])
    op.create_index("ix_delivery_trips_scheduled_date", "delivery_trips", ["scheduled_date"])
    op.create_index("ix_delivery_trips_status", "delivery_trips", ["status"])
    op.create_index("ix_delivery_trips_vehicle_number", "delivery_trips", ["vehicle_number"])
    op.create_table(
        "delivery_trip_stops",
        sa.Column(
            "delivery_id",
            sa.String(36),
            sa.ForeignKey("delivery_slips.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("trip_id", sa.String(36), sa.ForeignKey("delivery_trips.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("trip_id", "sequence", name="uq_trip_sequence"),
    )
    op.create_index("ix_delivery_trip_stops_trip_id", "delivery_trip_stops", ["trip_id"])
    op.create_table(
        "delivery_trip_loads",
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("delivery_trips.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("cylinder_type", sa.String(40), primary_key=True, nullable=False),
        sa.Column("merchant_id", sa.String(36), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("remaining_filled", sa.BigInteger(), nullable=False),
        sa.Column("current_empty", sa.BigInteger(), nullable=False),
        sa.Column("loaded_filled", sa.BigInteger(), nullable=False),
        sa.Column("opening_empty", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "loaded_filled >= 0 AND opening_empty >= 0 AND remaining_filled >= 0 AND current_empty >= 0",
            name="trip_load_nonnegative",
        ),
    )
    op.create_index("ix_delivery_trip_loads_merchant_id", "delivery_trip_loads", ["merchant_id"])
    op.create_index(
        "ix_trip_custody_active", "delivery_trip_loads", ["merchant_id", "active", "cylinder_type"]
    )
    table = sa.table(
        "logistics_settings",
        sa.column("scope", sa.String),
        sa.column("config", sa.Text),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        table,
        [
            {
                "scope": "platform",
                "config": '{"priorities":[{"code":"HIGH","label":"High","rank":0,"color":"#DC2626"},{"code":"MEDIUM","label":"Medium","rank":1,"color":"#D97706"},{"code":"LOW","label":"Low","rank":2,"color":"#2563EB"}],"defaultOrigin":null,"defaultDestination":null,"defaultPriority":"MEDIUM","maxStops":20,"optimizationEnabled":false,"priorityFirst":true,"requireSeparateReturnVerifier":true,"requireOdometer":false,"maxLoadCylinders":500}',
                "updated_at": datetime(2026, 11, 4, tzinfo=UTC),
            }
        ],
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM delivery_trips")).scalar():
        raise RuntimeError("Cannot remove logistics tables while trip history exists.")
    op.drop_table("delivery_trip_loads")
    op.drop_table("delivery_trip_stops")
    op.drop_table("delivery_trips")
    op.drop_table("logistics_settings")
    op.drop_index("ix_orders_priority_code", table_name="orders")
    op.drop_column("orders", "priority_code")
    op.drop_index("ix_customer_profiles_priority_code", table_name="customer_profiles")
    op.drop_column("customer_profiles", "priority_code")
