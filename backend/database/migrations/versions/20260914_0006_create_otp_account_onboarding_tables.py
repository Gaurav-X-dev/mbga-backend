"""create otp account onboarding tables

Revision ID: 20260914_0006
Revises: 20260914_0005
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260914_0006"
down_revision = "20260914_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mobile_number", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("login_channel", sa.String(length=30), nullable=False),
        sa.Column("otp_hash", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=100), nullable=True),
        sa.Column("device_type", sa.String(length=20), nullable=True),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_otp_challenges_mobile_number", "otp_challenges", ["mobile_number"])
    op.create_index("ix_otp_challenges_purpose", "otp_challenges", ["purpose"])
    op.create_index("ix_otp_challenges_login_channel", "otp_challenges", ["login_channel"])
    op.create_index("ix_otp_challenges_mobile_purpose_channel", "otp_challenges", ["mobile_number", "purpose", "login_channel"])
    op.create_index("ix_otp_challenges_expires_at", "otp_challenges", ["expires_at"])

    op.create_table(
        "merchants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("mobile_number", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("approval_status", sa.String(length=30), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_merchants_code", "merchants", ["code"], unique=True)
    op.create_index("ix_merchants_mobile_number", "merchants", ["mobile_number"], unique=True)
    op.create_index("ix_merchants_status", "merchants", ["status"])
    op.create_index("ix_merchants_approval_status", "merchants", ["approval_status"])
    op.create_index("ix_merchants_status_code", "merchants", ["status", "code"])

    op.create_table(
        "merchant_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("merchant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("staff_type", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "user_id", name="uq_merchant_user"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_merchant_users_merchant_id", "merchant_users", ["merchant_id"])
    op.create_index("ix_merchant_users_user_id", "merchant_users", ["user_id"])
    op.create_index("ix_merchant_users_status", "merchant_users", ["status"])
    op.create_index("ix_merchant_users_merchant_status", "merchant_users", ["merchant_id", "status"])

    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("merchant_id", sa.String(length=36), nullable=True),
        sa.Column("merchant_code", sa.String(length=80), nullable=True),
        sa.Column("customer_type", sa.String(length=40), nullable=True),
        sa.Column("mobile_number", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=True),
        sa.Column("gst_number", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("mobile_verified_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_customer_profiles_user_id", "customer_profiles", ["user_id"])
    op.create_index("ix_customer_profiles_merchant_id", "customer_profiles", ["merchant_id"])
    op.create_index("ix_customer_profiles_merchant_code", "customer_profiles", ["merchant_code"])
    op.create_index("ix_customer_profiles_mobile_number", "customer_profiles", ["mobile_number"], unique=True)
    op.create_index("ix_customer_profiles_status", "customer_profiles", ["status"])
    op.create_index("ix_customer_profiles_merchant_status", "customer_profiles", ["merchant_id", "status"])
    op.create_index("ix_customer_profiles_mobile", "customer_profiles", ["mobile_number"])

    op.create_table(
        "customer_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("document_number", sa.String(length=80), nullable=True),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=180), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("issue_date", sa.DateTime(), nullable=True),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customer_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_customer_documents_customer_id", "customer_documents", ["customer_id"])
    op.create_index("ix_customer_documents_document_type", "customer_documents", ["document_type"])
    op.create_index("ix_customer_documents_status", "customer_documents", ["status"])
    op.create_index("ix_customer_documents_customer_status", "customer_documents", ["customer_id", "status"])

    op.create_table(
        "delivery_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("merchant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("delivery_user_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("approval_status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_unicode_ci",
    )
    op.create_index("ix_delivery_profiles_merchant_id", "delivery_profiles", ["merchant_id"])
    op.create_index("ix_delivery_profiles_user_id", "delivery_profiles", ["user_id"])
    op.create_index("ix_delivery_profiles_delivery_user_type", "delivery_profiles", ["delivery_user_type"])
    op.create_index("ix_delivery_profiles_status", "delivery_profiles", ["status"])
    op.create_index("ix_delivery_profiles_approval_status", "delivery_profiles", ["approval_status"])
    op.create_index("ix_delivery_profiles_merchant_status", "delivery_profiles", ["merchant_id", "status"])


def downgrade() -> None:
    op.drop_table("delivery_profiles")
    op.drop_table("customer_documents")
    op.drop_table("customer_profiles")
    op.drop_table("merchant_users")
    op.drop_table("merchants")
    op.drop_table("otp_challenges")
