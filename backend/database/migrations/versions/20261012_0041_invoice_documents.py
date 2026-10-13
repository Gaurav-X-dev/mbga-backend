"""Universal immutable invoice documents and merchant print settings.

Revision ID: 20261012_0041
Revises: 20261010_0040
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_0041"
down_revision = "20261010_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No server defaults on TEXT: MySQL rejects those on several supported versions.
    op.add_column("invoices", sa.Column("document_snapshot", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("irn", sa.String(length=120), nullable=True))
    op.add_column("invoices", sa.Column("acknowledgement_number", sa.String(length=80), nullable=True))
    op.add_column("invoices", sa.Column("acknowledgement_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("eway_bill_number", sa.String(length=80), nullable=True))
    op.add_column("invoices", sa.Column("eway_bill_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("transport_document_number", sa.String(length=100), nullable=True))
    op.add_column("invoices", sa.Column("lr_number", sa.String(length=100), nullable=True))
    op.add_column("invoices", sa.Column("terms_of_delivery", sa.String(length=500), nullable=True))

    for name, column in (
        ("invoice_pan", sa.String(length=20)),
        ("invoice_bank_name", sa.String(length=160)),
        ("invoice_bank_account_name", sa.String(length=160)),
        ("invoice_bank_account_number", sa.String(length=80)),
        ("invoice_bank_ifsc", sa.String(length=30)),
        ("invoice_logo_url", sa.String(length=500)),
        ("invoice_signature_url", sa.String(length=500)),
        ("invoice_terms", sa.Text()),
        ("invoice_declaration", sa.Text()),
    ):
        op.add_column("merchants", sa.Column(name, column, nullable=True))
    op.add_column(
        "merchants",
        sa.Column("invoice_hsn_sac", sa.String(length=30), nullable=False, server_default="271119"),
    )


def downgrade() -> None:
    for name in (
        "invoice_hsn_sac", "invoice_declaration", "invoice_terms", "invoice_signature_url",
        "invoice_logo_url", "invoice_bank_ifsc", "invoice_bank_account_number",
        "invoice_bank_account_name", "invoice_bank_name", "invoice_pan",
    ):
        op.drop_column("merchants", name)
    for name in (
        "terms_of_delivery", "lr_number", "transport_document_number", "eway_bill_date",
        "eway_bill_number", "acknowledgement_date", "acknowledgement_number", "irn",
        "document_snapshot",
    ):
        op.drop_column("invoices", name)
