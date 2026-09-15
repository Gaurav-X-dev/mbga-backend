"""ensure user role validity lookup index

Revision ID: 20260914_0004
Revises: 20260914_0003
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0004"
down_revision = "20260914_0003"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_user_roles_user_active_validity"


def _index_exists() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == INDEX_NAME for index in inspector.get_indexes("user_roles"))


def upgrade() -> None:
    if not _index_exists():
        op.create_index(
            INDEX_NAME,
            "user_roles",
            ["user_id", "is_active", "valid_from", "valid_until"],
            unique=False,
        )


def downgrade() -> None:
    if _index_exists():
        op.drop_index(INDEX_NAME, table_name="user_roles")
