"""create approved RBAC tables

Revision ID: 20260914_0002
Revises: 20260914_0001
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0002"
down_revision = "20260914_0001"
branch_labels = None
depends_on = None

MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("role_type", sa.String(length=20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_roles_code", "roles", ["code"], unique=True)
    op.create_index("ix_roles_active_code", "roles", ["is_active", "code"], unique=False)

    op.create_table(
        "permissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)
    op.create_index("ix_permissions_active_code", "permissions", ["is_active", "code"], unique=False)
    op.create_index("ix_permissions_module", "permissions", ["module"], unique=False)
    op.create_index("ix_permissions_action", "permissions", ["action"], unique=False)
    op.create_index("ix_permissions_module_action", "permissions", ["module", "action"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission_id_permissions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"], unique=False)
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"], unique=False)

    op.create_table(
        "role_login_channels",
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("login_channel", sa.String(length=30), nullable=False),
        sa.Column("is_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_login_channels_role_id_roles", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("role_id", "login_channel"),
        sa.UniqueConstraint("role_id", "login_channel", name="uq_role_login_channel"),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "ix_role_login_channels_role_channel_allowed",
        "role_login_channels",
        ["role_id", "login_channel", "is_allowed"],
        unique=False,
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("assigned_by", sa.String(length=36), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.String(length=36), nullable=False, server_default="global"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_user_roles_role_id_roles", ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "role_id", "scope_type", "scope_id", name="uq_user_role_scope"),
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"], unique=False)
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"], unique=False)
    op.create_index(
        "ix_user_roles_user_active_validity",
        "user_roles",
        ["user_id", "is_active", "valid_from", "valid_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("user_roles")

    op.drop_table("role_login_channels")

    op.drop_table("role_permissions")

    op.drop_index("ix_permissions_module_action", table_name="permissions")
    op.drop_index("ix_permissions_action", table_name="permissions")
    op.drop_index("ix_permissions_module", table_name="permissions")
    op.drop_index("ix_permissions_active_code", table_name="permissions")
    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("ix_roles_active_code", table_name="roles")
    op.drop_index("ix_roles_code", table_name="roles")
    op.drop_table("roles")
