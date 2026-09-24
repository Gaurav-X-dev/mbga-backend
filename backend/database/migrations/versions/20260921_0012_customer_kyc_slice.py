"""Customer registration, delivery sites, KYC applications and document metadata.

Additive throughout. Every new column on an existing table is nullable or carries a server
default, so rows written before this migration stay valid and the deploy needs no backfill.

The one widening change is customer_documents.customer_id, which becomes nullable so an
upload can be staged before the customer profile exists. Its downgrade removes the staged
rows that could not exist under the old shape - see the note there.

Revision ID: 20260921_0012
Revises: 20260921_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0012"
down_revision = "20260921_0011"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    _extend_customer_profiles()
    _extend_customer_documents()
    _create_delivery_sites()
    _create_kyc_applications()
    _create_code_sequences()
    _create_notification_outbox()


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_pending", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_table("customer_code_sequences")
    op.drop_index("ix_kyc_applications_merchant_status", table_name="kyc_applications")
    op.drop_table("kyc_applications")
    op.drop_index("ix_customer_delivery_sites_customer_primary", table_name="customer_delivery_sites")
    op.drop_table("customer_delivery_sites")
    _revert_customer_documents()
    _revert_customer_profiles()


# --- customer_profiles ---------------------------------------------------------------------

PROFILE_COLUMNS = [
    ("code", sa.String(40), {"nullable": True}),
    ("owner_name", sa.String(160), {"nullable": True}),
    ("email", sa.String(255), {"nullable": True}),
    ("pricing_tier", sa.String(30), {"nullable": False, "server_default": "STANDARD"}),
    ("address_line1", sa.String(255), {"nullable": True}),
    ("address_line2", sa.String(255), {"nullable": True}),
    ("address_city", sa.String(120), {"nullable": True}),
    ("address_state", sa.String(120), {"nullable": True}),
    ("address_pincode", sa.String(6), {"nullable": True}),
    ("kyc_status", sa.String(30), {"nullable": False, "server_default": "NOT_SUBMITTED"}),
    ("approved_at", TIMESTAMP, {"nullable": True}),
    ("registered_at", TIMESTAMP, {"nullable": True}),
]

# Rows written before this migration have no kyc_status. Deriving it from the account status
# they already carry keeps the two fields consistent, instead of reporting every existing
# approved customer as NOT_SUBMITTED.
KYC_BACKFILL = [
    ("VERIFIED", "APPROVED"),
    ("PENDING", "UNDER_REVIEW"),
    ("REJECTED", "REJECTED"),
]


def _extend_customer_profiles() -> None:
    for name, type_, kwargs in PROFILE_COLUMNS:
        op.add_column("customer_profiles", sa.Column(name, type_, **kwargs))
    op.create_unique_constraint("uq_customer_profiles_code", "customer_profiles", ["code"])
    op.create_index("ix_customer_profiles_kyc_status", "customer_profiles", ["kyc_status"])
    for kyc_status, account_status in KYC_BACKFILL:
        op.execute(
            sa.text("UPDATE customer_profiles SET kyc_status = :kyc WHERE status = :account").bindparams(
                kyc=kyc_status, account=account_status
            )
        )
    op.execute(sa.text("UPDATE customer_profiles SET registered_at = created_at WHERE registered_at IS NULL"))


def _revert_customer_profiles() -> None:
    op.drop_index("ix_customer_profiles_kyc_status", table_name="customer_profiles")
    op.drop_constraint("uq_customer_profiles_code", "customer_profiles", type_="unique")
    for name, _type, _kwargs in reversed(PROFILE_COLUMNS):
        op.drop_column("customer_profiles", name)


# --- customer_documents --------------------------------------------------------------------

DOCUMENT_COLUMNS = [
    ("file_id", sa.String(60), {"nullable": True}),
    ("owner_user_id", sa.String(36), {"nullable": True}),
    ("merchant_id", sa.String(36), {"nullable": True}),
    ("uploaded_by_user_id", sa.String(36), {"nullable": True}),
    ("number_encrypted", sa.Text(), {"nullable": True}),
    ("number_masked", sa.String(60), {"nullable": True}),
    ("number_lookup_hash", sa.String(64), {"nullable": True}),
    ("checksum_sha256", sa.String(64), {"nullable": True}),
    ("scan_status", sa.String(20), {"nullable": False, "server_default": "SKIPPED"}),
    ("storage_provider", sa.String(30), {"nullable": False, "server_default": "local"}),
    ("finalized_at", TIMESTAMP, {"nullable": True}),
]

DOCUMENT_INDEXES = [
    ("ix_customer_documents_owner_type", ["owner_user_id", "document_type"]),
    ("ix_customer_documents_lookup_hash", ["number_lookup_hash"]),
    ("ix_customer_documents_checksum", ["checksum_sha256"]),
    ("ix_customer_documents_merchant", ["merchant_id"]),
]


def _extend_customer_documents() -> None:
    for name, type_, kwargs in DOCUMENT_COLUMNS:
        op.add_column("customer_documents", sa.Column(name, type_, **kwargs))
    op.create_unique_constraint("uq_customer_documents_file_id", "customer_documents", ["file_id"])
    for index_name, columns in DOCUMENT_INDEXES:
        op.create_index(index_name, "customer_documents", columns)
    # A staged upload has no customer yet, so the column has to accept NULL.
    op.alter_column("customer_documents", "customer_id", existing_type=sa.String(36), nullable=True)


def _revert_customer_documents() -> None:
    # Staged uploads have no customer and cannot be represented once the column is NOT NULL
    # again. They are unreferenced working files, so removing them is the correct reversal:
    # no finalized document is ever touched, because finalizing always sets customer_id.
    op.execute(sa.text("DELETE FROM customer_documents WHERE customer_id IS NULL"))
    op.alter_column("customer_documents", "customer_id", existing_type=sa.String(36), nullable=False)
    for index_name, _columns in reversed(DOCUMENT_INDEXES):
        op.drop_index(index_name, table_name="customer_documents")
    op.drop_constraint("uq_customer_documents_file_id", "customer_documents", type_="unique")
    for name, _type, _kwargs in reversed(DOCUMENT_COLUMNS):
        op.drop_column("customer_documents", name)


# --- new tables ----------------------------------------------------------------------------


def _create_delivery_sites() -> None:
    op.create_table(
        "customer_delivery_sites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False, index=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("address_line1", sa.String(255), nullable=False),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("address_city", sa.String(120), nullable=False),
        sa.Column("address_state", sa.String(120), nullable=False),
        sa.Column("address_pincode", sa.String(6), nullable=False),
        sa.Column("contact_name", sa.String(160), nullable=True),
        sa.Column("contact_mobile", sa.String(20), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
    op.create_index(
        "ix_customer_delivery_sites_customer_primary",
        "customer_delivery_sites",
        ["customer_id", "is_primary"],
    )


def _create_kyc_applications() -> None:
    op.create_table(
        "kyc_applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customer_profiles.id"), nullable=False, index=True),
        sa.Column("merchant_id", sa.String(36), nullable=True, index=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("submitted_at", TIMESTAMP, nullable=False),
        sa.Column("reviewed_at", TIMESTAMP, nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(36), nullable=True),
        sa.Column("reviewed_by_name", sa.String(160), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("submitted_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
    op.create_index(
        "ix_kyc_applications_merchant_status",
        "kyc_applications",
        ["merchant_id", "status", "submitted_at"],
    )


def _create_code_sequences() -> None:
    op.create_table(
        "customer_code_sequences",
        sa.Column("prefix", sa.String(20), primary_key=True),
        sa.Column("next_value", sa.BigInteger(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )


def _create_notification_outbox() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False, index=True),
        sa.Column("recipient_kind", sa.String(20), nullable=False),
        sa.Column("recipient_id", sa.String(36), nullable=False, index=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("delivered_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        # Makes a retried submit or a repeated decision idempotent at the notification level:
        # the same event for the same entity and recipient can only be queued once.
        sa.UniqueConstraint(
            "event_type", "entity_type", "entity_id", "recipient_kind", "recipient_id",
            name="uq_notification_outbox_event",
        ),
    )
    op.create_index("ix_notification_outbox_pending", "notification_outbox", ["delivered_at", "created_at"])
