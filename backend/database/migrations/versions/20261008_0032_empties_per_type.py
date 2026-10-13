"""Record which size of empty cylinder came back, not just how many.

`delivery_slips.empties_collected` is one number across every cylinder type. That is enough for
the stock ledger, which books empties as a single movement, but it is all the platform knew - so
the driver's receipt had no per-type figures to print and fell back to listing the *delivered*
lines in the empties column. A handover of two 5 KG and one 19 KG, with two empties taken,
printed "Total: 2" above rows adding to 3.

The Delivery App has always sent `collectedEmpties` per type on `/confirm`. It was summed on
arrival and the breakdown thrown away. This gives it somewhere to live, beside
`delivered_quantity`, which is on this table for exactly the same reason.

Null means nothing was recorded per type: a slip from before today, or one the office confirmed
itself. The slip's own total stays authoritative and is not touched - this adds detail beneath
it rather than replacing it, so no backfill can invent a split that was never recorded.

Revision ID: 20261008_0032
Revises: 20261007_0031
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0032"
down_revision = "20261007_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "delivery_slip_items", sa.Column("empties_collected", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("delivery_slip_items", "empties_collected")
