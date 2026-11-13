"""Direct branch permissions; retire additional-user invitations without removing history."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0077"
down_revision = "20261112_0076"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customer_brand_outlets", sa.Column("permissions", sa.Text(), nullable=True))
    op.execute(
        "UPDATE customer_memberships SET status = 'REVOKED' WHERE status IN ('INVITED', 'ACTIVE')"
    )


def downgrade():
    op.drop_column("customer_brand_outlets", "permissions")
    # Retired invitations/access are never silently restored.
