"""Store driver-location timestamps as Asia/Kolkata wall time.

Revision ID: 20261026_0055
Revises: 20261023_0054

MySQL DATETIME does not retain a timezone offset. Location timestamps introduced by 0054 were
written as UTC wall time; convert only those tracking fields to IST (+05:30). Other application
timestamps remain untouched.
"""

from alembic import op

revision = "20261026_0055"
down_revision = "20261023_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE driver_location_logs "
        "SET recorded_at = DATE_ADD(recorded_at, INTERVAL 330 MINUTE), "
        "created_at = DATE_ADD(created_at, INTERVAL 330 MINUTE)"
    )
    op.execute(
        "UPDATE delivery_profiles "
        "SET last_ping_at = DATE_ADD(last_ping_at, INTERVAL 330 MINUTE) "
        "WHERE last_ping_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE driver_location_logs "
        "SET recorded_at = DATE_SUB(recorded_at, INTERVAL 330 MINUTE), "
        "created_at = DATE_SUB(created_at, INTERVAL 330 MINUTE)"
    )
    op.execute(
        "UPDATE delivery_profiles "
        "SET last_ping_at = DATE_SUB(last_ping_at, INTERVAL 330 MINUTE) "
        "WHERE last_ping_at IS NOT NULL"
    )
