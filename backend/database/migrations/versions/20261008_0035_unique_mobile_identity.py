"""Merge duplicate phone identities and make a phone globally unique.

Revision ID: 20261008_0035
Revises: 20261008_0034
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261008_0035"
down_revision = "20261008_0034"
branch_labels = None
depends_on = None


def _exec(sql: str, **params) -> None:
    op.get_bind().execute(sa.text(sql), params)


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_mobiles = bind.execute(
        sa.text(
            """SELECT mobile_number FROM users
               WHERE mobile_number IS NOT NULL AND mobile_number <> ''
               GROUP BY mobile_number HAVING COUNT(*) > 1"""
        )
    ).scalars().all()

    for mobile in duplicate_mobiles:
        rows = bind.execute(
            sa.text(
                """SELECT id FROM users WHERE mobile_number = :mobile
                   ORDER BY (status = 'ACTIVE') DESC, created_at, id"""
            ),
            {"mobile": mobile},
        ).scalars().all()
        master, *duplicates = rows
        for duplicate in duplicates:
            # Preserve the richer identity metadata without changing the master account state.
            _exec(
                """UPDATE users master JOIN users old ON old.id = :old
                   SET master.full_name = COALESCE(master.full_name, old.full_name),
                       master.updated_at = COALESCE(master.updated_at, :now)
                   WHERE master.id = :master""",
                old=duplicate,
                master=master,
                now=datetime.now(UTC),
            )

            # Composite unique keys need duplicate associations removed before repointing.
            _exec(
                """DELETE old FROM user_roles old JOIN user_roles keep
                     ON keep.user_id = :master AND old.user_id = :old
                    AND keep.role_id = old.role_id AND keep.scope_type = old.scope_type
                    AND keep.scope_id = old.scope_id""",
                old=duplicate,
                master=master,
            )
            _exec("UPDATE user_roles SET user_id=:master WHERE user_id=:old", old=duplicate, master=master)
            _exec(
                """DELETE old FROM merchant_users old JOIN merchant_users keep
                     ON keep.user_id = :master AND old.user_id = :old
                    AND keep.merchant_id = old.merchant_id""",
                old=duplicate,
                master=master,
            )
            _exec("UPDATE merchant_users SET user_id=:master WHERE user_id=:old", old=duplicate, master=master)
            _exec("UPDATE customer_profiles SET user_id=:master WHERE user_id=:old", old=duplicate, master=master)
            _exec("UPDATE delivery_profiles SET user_id=:master WHERE user_id=:old", old=duplicate, master=master)

            # Old credentials must not silently become credentials for a merged account.
            _exec(
                """UPDATE login_sessions SET user_id=:master,
                       revoked_at=COALESCE(revoked_at, :now),
                       revoked_reason=COALESCE(revoked_reason, 'IDENTITY_MERGED')
                   WHERE user_id=:old""",
                old=duplicate,
                master=master,
                now=datetime.now(UTC),
            )

            # Per-user notification read state also has a composite primary key.
            _exec(
                """DELETE old FROM notification_reads old JOIN notification_reads keep
                     ON keep.user_id=:master AND old.user_id=:old
                    AND keep.notification_id=old.notification_id""",
                old=duplicate,
                master=master,
            )
            _exec("UPDATE notification_reads SET user_id=:master WHERE user_id=:old", old=duplicate, master=master)

            # Historical actor references are intentionally repointed so lookups keep working.
            actor_columns = (
                ("audit_logs", "actor_user_id"),
                ("idempotency_records", "actor_user_id"),
                ("inventory_movements", "recorded_by_user_id"),
                ("expenses", "recorded_by_user_id"),
                ("payments", "collected_by_user_id"),
                ("orders", "created_by_user_id"),
                ("order_status_history", "changed_by_user_id"),
                ("delivery_slips", "driver_user_id"),
                ("delivery_slips", "helper_user_id"),
                ("delivery_slips", "created_by_user_id"),
                ("platform_settings", "updated_by_user_id"),
            )
            inspector = sa.inspect(bind)
            tables = set(inspector.get_table_names())
            for table, column in actor_columns:
                if table in tables and column in {c["name"] for c in inspector.get_columns(table)}:
                    _exec(f"UPDATE `{table}` SET `{column}`=:master WHERE `{column}`=:old", old=duplicate, master=master)

            _exec("DELETE FROM users WHERE id=:old", old=duplicate)

    op.create_unique_constraint("uq_users_mobile_number", "users", ["mobile_number"])


def downgrade() -> None:
    op.drop_constraint("uq_users_mobile_number", "users", type_="unique")
