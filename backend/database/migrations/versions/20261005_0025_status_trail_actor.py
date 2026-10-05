"""Record what an order status moved from, who moved it, and from which app.

The trail already named the new status and the person. That is enough to render a timeline and
not enough to answer the question it was actually needed for: an order that was cancelled and
then showed as out for delivery. Reading the previous row works only when every row is present
and correctly ordered, which is precisely what is in doubt when two requests raced.

`previous_status` makes one row answer it on its own. `changed_by_role` and `source` say what the
actor was acting as and which app they used; both are taken from the session's login channel, so
neither can be claimed by a client sending its own field.

All three are nullable with no backfill. Existing rows genuinely do not know where they came
from, and inventing a previous status for them by walking the table would put guesses in an
append-only record - the one place a guess must never go.

Revision ID: 20261005_0025
Revises: 20261001_0024
"""

import sqlalchemy as sa
from alembic import op

revision = "20261005_0025"
down_revision = "20261001_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_status_history",
        sa.Column("previous_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "order_status_history",
        sa.Column("changed_by_role", sa.String(40), nullable=True),
    )
    op.add_column(
        "order_status_history",
        sa.Column("source", sa.String(40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_status_history", "source")
    op.drop_column("order_status_history", "changed_by_role")
    op.drop_column("order_status_history", "previous_status")
