"""Assignable customer permanent-delete permission; super admin only by default."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "20261112_0076"
down_revision = "20261111_0075"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    permission_id = connection.scalar(
        sa.text("SELECT id FROM permissions WHERE code = 'customers.delete'")
    )
    now = datetime.now(UTC)
    if permission_id is None:
        permission_id = str(uuid4())
        connection.execute(
            sa.text("""
            INSERT INTO permissions
            (id, name, code, module, action, description, is_system, is_active, created_at, updated_at)
            VALUES (:id, 'Permanently delete customers', 'customers.delete', 'customers', 'delete',
            'Permanently delete customers without business records. Assign only to trusted staff.',
            true, true, :now, :now)
        """),
            {"id": permission_id, "now": now},
        )
    connection.execute(
        sa.text("""
        INSERT INTO role_permissions (role_id, permission_id, granted_at, granted_by)
        SELECT id, :permission_id, :now, NULL FROM roles
        WHERE code = 'super_admin' AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = roles.id AND rp.permission_id = :permission_id
        )
    """),
        {"permission_id": permission_id, "now": now},
    )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text("""
        DELETE FROM role_permissions WHERE permission_id IN
        (SELECT id FROM permissions WHERE code = 'customers.delete')
    """)
    )
    connection.execute(sa.text("DELETE FROM permissions WHERE code = 'customers.delete'"))
