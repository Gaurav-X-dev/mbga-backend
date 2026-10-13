"""Take `capacity` off a vehicle.

It was added on the reasoning that the office might plan a round against it. The office does
not know these figures - a van's real load depends on the cylinder mix and what the yard says -
so the column was never going to be filled, and a field nobody fills is a field that reads as
missing data on every screen. The merchant app was already printing it beside the plate, which
is how it came up.

Nothing is lost: no row ever carried a value, because the only writer was an API field the
panel had just started sending and the service never stored.

Revision ID: 20261008_0037
Revises: 20261008_0036
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0037"
down_revision = "20261008_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("vehicles", "capacity")


def downgrade() -> None:
    op.add_column("vehicles", sa.Column("capacity", sa.Integer(), nullable=True))
