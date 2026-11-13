"""Let a job be an e-Way Bill on its own, with no IRN behind it.

An e-Way Bill accompanies goods worth more than fifty thousand rupees whoever is buying
them. Until now a job was only ever queued when the buyer had a GSTIN, so an over-threshold
sale to an unregistered customer filed nothing at all - a compliance gap, not a cosmetic one.

`with_irn` records which of the two provider APIs a job goes to, and `eway_bill_number`
holds the result for the route that has no IRN to hang it off.

`with_irn` defaults to 1 on purpose: every row that exists when this runs was queued under
the old rule, which only queued invoices that had a buyer GSTIN. They are all IRN jobs, and
the default says so without a data migration.

Renumbered from 20261030_0066: the deployment server had taken that same revision
id for competitor pricing while this branch was away, and two migrations cannot
share one id - alembic refuses every command when they do. This one carries no
data, only two columns, so moving it to the end of the chain changes nothing
about what it does.

Revision ID: 20261113_0079
Revises: 20261112_0078
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0079"
down_revision = "20261112_0078"
branch_labels = None
depends_on = None

TABLE = "einvoice_jobs"


def _columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if TABLE not in sa.inspect(bind).get_table_names():
        # The e-invoice slice has not been installed on this database yet; 0059 creates the
        # table with both columns already on it.
        return

    existing = _columns(bind)
    if "with_irn" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "with_irn",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
        )
    if "eway_bill_number" not in existing:
        op.add_column(TABLE, sa.Column("eway_bill_number", sa.String(length=20), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if TABLE not in sa.inspect(bind).get_table_names():
        return
    existing = _columns(bind)
    if "eway_bill_number" in existing:
        op.drop_column(TABLE, "eway_bill_number")
    if "with_irn" in existing:
        op.drop_column(TABLE, "with_irn")
