"""Hold the order cut-off in a row the admin panel can change.

It was a constant in `orders/cutoff.py`, so moving the godown's day from 16:00 to 18:00 meant a
release. It is an operating decision an operator makes during the working day, not a fact about
the deployment, so it belongs somewhere they can reach.

One row with typed columns rather than a key/value table: every reader would otherwise have to
parse a string and decide what to do when it is not a number, and the database would have no
opinion about an hour of 25. A column per setting costs a migration each time, which is the
cheaper half of that trade.

The row is seeded here with 16, the cut-off the platform has always had, so nothing changes until
somebody decides it should. `platform_settings.view` and `platform_settings.manage` are seeded
with the other permissions; super admin receives every permission, so the first operator can
reach the screen without a grant.

Revision ID: 20261005_0026
Revises: 20261005_0025
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261005_0026"
down_revision = "20261005_0025"
branch_labels = None
depends_on = None

SINGLETON_ID = "platform"
DEFAULT_ORDER_CUTOFF_HOUR = 16


def upgrade() -> None:
    table = op.create_table(
        "platform_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "order_cutoff_hour",
            sa.Integer(),
            nullable=False,
            server_default=str(DEFAULT_ORDER_CUTOFF_HOUR),
        ),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.Column("updated_by_name", sa.String(160), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Seeded rather than created on first read, so a fresh deployment's first order does not
    # depend on a write succeeding. The service still creates it if it is missing - a database
    # restored from a dump taken before this existed should not 500 on every order.
    op.bulk_insert(
        table,
        [
            {
                "id": SINGLETON_ID,
                "order_cutoff_hour": DEFAULT_ORDER_CUTOFF_HOUR,
                "updated_by_user_id": None,
                "updated_by_name": None,
                "updated_at": datetime.now(UTC).replace(tzinfo=None),
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
