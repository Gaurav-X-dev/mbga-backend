"""Queue table for GST e-invoice (IRN / e-Way Bill) filing.

Revision ID: 20261027_0059
Revises: 20261027_0058

No existing table is altered. The IRN, acknowledgement and e-Way Bill columns this writes
into already exist on `invoices` - they were added when those references were still typed in
by hand, and this slice fills them from the portal instead.

Idempotent: re-running on a database that already has the table does nothing, so the servers
and the repo can be brought back into line without a hand-edited revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0059"
down_revision = "20261027_0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "einvoice_jobs" in inspector.get_table_names():
        return
    op.create_table(
        "einvoice_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("merchant_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("with_eway_bill", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("last_response", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # One job per invoice: a retried delivery confirmation must not ask the portal for
        # two IRNs against one document.
        sa.UniqueConstraint("invoice_id", name="uq_einvoice_jobs_invoice"),
    )
    op.create_index("ix_einvoice_jobs_invoice_id", "einvoice_jobs", ["invoice_id"])
    op.create_index("ix_einvoice_jobs_merchant_id", "einvoice_jobs", ["merchant_id"])
    op.create_index("ix_einvoice_jobs_status", "einvoice_jobs", ["status"])
    # The worker's query: what is due, oldest first.
    op.create_index("ix_einvoice_jobs_due", "einvoice_jobs", ["status", "next_attempt_at"])
    # The admin screen: this merchant's failures.
    op.create_index(
        "ix_einvoice_jobs_merchant_status", "einvoice_jobs", ["merchant_id", "status"]
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "einvoice_jobs" not in inspector.get_table_names():
        return
    op.drop_index("ix_einvoice_jobs_merchant_status", table_name="einvoice_jobs")
    op.drop_index("ix_einvoice_jobs_due", table_name="einvoice_jobs")
    op.drop_index("ix_einvoice_jobs_status", table_name="einvoice_jobs")
    op.drop_index("ix_einvoice_jobs_merchant_id", table_name="einvoice_jobs")
    op.drop_index("ix_einvoice_jobs_invoice_id", table_name="einvoice_jobs")
    op.drop_table("einvoice_jobs")
