"""Optional structured competitor depot address and coordinates."""

import sqlalchemy as sa
from alembic import op

revision = "20261102_0067"
down_revision = "20261030_0066"
branch_labels = None
depends_on = None


def upgrade():
    for name, length in [
        ("depot_line1", 255),
        ("depot_line2", 255),
        ("depot_city", 100),
        ("depot_state", 100),
        ("depot_pincode", 6),
    ]:
        op.add_column("competitors", sa.Column(name, sa.String(length), nullable=True))
    op.add_column("competitors", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("competitors", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))


def downgrade():
    for name in [
        "longitude",
        "latitude",
        "depot_pincode",
        "depot_state",
        "depot_city",
        "depot_line2",
        "depot_line1",
    ]:
        op.drop_column("competitors", name)
