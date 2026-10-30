"""Optional destination for fuel expenses and fuel-sheet reporting."""
from alembic import op
import sqlalchemy as sa
revision = "20261028_0062"
down_revision = "20261028_0061"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("expenses", sa.Column("destination",sa.String(160),nullable=True))


def downgrade():
    op.drop_column("expenses","destination")
