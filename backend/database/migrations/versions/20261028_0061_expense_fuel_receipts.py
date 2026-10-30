"""Optional fuel telemetry and private expense receipts; preserves existing rows."""
from alembic import op
import sqlalchemy as sa
revision = "20261028_0061"
down_revision = "20261027_0060"
branch_labels = None
depends_on = None


def upgrade():
    for name, datatype in [
        ("vehicle_id", sa.String(36)), ("vehicle_number", sa.String(50)),
        ("driver_id", sa.String(36)), ("driver_name", sa.String(160)),
        ("fuel_type", sa.String(20)), ("km_reading", sa.Numeric(12, 2)),
        ("distance", sa.Numeric(12, 2)), ("liters", sa.Numeric(12, 3)),
        ("receipt_storage_key", sa.String(255)), ("receipt_content_type", sa.String(80)),
    ]:
        op.add_column("expenses", sa.Column(name, datatype, nullable=True))


def downgrade():
    for name in ["receipt_content_type", "receipt_storage_key", "liters", "distance", "km_reading", "fuel_type", "driver_name", "driver_id", "vehicle_number", "vehicle_id"]:
        op.drop_column("expenses", name)
