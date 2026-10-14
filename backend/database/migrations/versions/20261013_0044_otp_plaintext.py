"""Keep the OTP in the clear so a support screen can print it.

Revision ID: 20261013_0044
Revises: 20261013_0043

Asked for after the SMS credit ran out: with no message arriving nobody could sign in, and the
office wanted to read the code off an admin screen instead.

The column is the whole trade. Until now a challenge held a one-way hash and the code existed
only in transit, so a copy of this table - or one of the backups taken from it - could not be
used to sign in as anybody. With this filled, it can.

It is written only while `OTP_LOG_PLAINTEXT_ENABLED` is on. Turning that off stops new rows
from carrying a code; `downgrade()` drops the column and every code still in it.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0044"
down_revision = "20261013_0043"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    """Whether `otp_plain` is already on the table.

    Asked rather than assumed because production already has the column: it was added by hand
    when this migration could not run - its parent revision was still sitting on a developer's
    machine - and the screen was wanted that afternoon. Running `ADD COLUMN` against it would
    fail, and take the rest of the upgrade down with it.

    Checked through the inspector rather than `ADD COLUMN IF NOT EXISTS`, which MariaDB accepts
    and MySQL 8 does not; this runs on both.
    """
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == "otp_plain" for column in inspector.get_columns("otp_challenges"))


def upgrade() -> None:
    if not _has_column():
        op.add_column("otp_challenges", sa.Column("otp_plain", sa.String(10), nullable=True))


def downgrade() -> None:
    if _has_column():
        op.drop_column("otp_challenges", "otp_plain")
