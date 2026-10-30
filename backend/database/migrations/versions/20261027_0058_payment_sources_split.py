"""Split merchant payments, delivery source, and customer payment display numbers.

Revision ID: 20261027_0058
Revises: 20261026_0057
"""
import sqlalchemy as sa
from alembic import op

revision = "20261027_0058"
down_revision = "20261026_0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("cash_amount", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("upi_amount", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("delivery_id", sa.String(36), nullable=True))
    op.create_index("ix_payments_delivery_id", "payments", ["delivery_id"])
    op.create_foreign_key("fk_payments_delivery", "payments", "delivery_slips", ["delivery_id"], ["id"])
    op.add_column("payment_collections", sa.Column("payment_number", sa.String(30), nullable=True))
    op.execute("UPDATE payments SET cash_amount = CASE WHEN mode = 'CASH' THEN amount_collected ELSE 0 END, "
               "upi_amount = CASE WHEN mode = 'UPI' THEN amount_collected ELSE 0 END")
    # Historical delivery rows have this server-generated note. Match tenant, customer,
    # and collector as well; ambiguous matches stay unclassified rather than misassigned.
    op.execute("""
        UPDATE payments p JOIN (
            SELECT p0.id AS payment_id, MIN(d.id) AS delivery_id
            FROM payments p0 JOIN delivery_slips d
              ON d.merchant_id = p0.merchant_id AND d.customer_id = p0.customer_id
             AND p0.note = CONCAT('Collected on delivery ', d.order_number)
             AND p0.collected_by_user_id = d.driver_user_id
             AND p0.collection_id IS NULL
            GROUP BY p0.id HAVING COUNT(*) = 1
        ) matched ON matched.payment_id = p.id
        SET p.delivery_id = matched.delivery_id
    """)
    # Reuse an existing issued number for old customer transactions; new submissions
    # allocate a parent number from the same merchant counter.
    op.execute("""
        UPDATE payment_collections c JOIN (
            SELECT collection_id, MIN(payment_number) AS payment_number
            FROM payments WHERE collection_id IS NOT NULL GROUP BY collection_id
        ) p ON p.collection_id = c.id SET c.payment_number = p.payment_number
    """)
    op.create_check_constraint(
        "ck_payments_split_amounts", "payments",
        "mode <> 'SPLIT' OR (cash_amount IS NOT NULL AND upi_amount IS NOT NULL "
        "AND cash_amount > 0 AND upi_amount > 0 "
        "AND cash_amount + upi_amount = amount_collected)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_payments_split_amounts", "payments", type_="check")
    op.drop_column("payment_collections", "payment_number")
    op.drop_constraint("fk_payments_delivery", "payments", type_="foreignkey")
    op.drop_index("ix_payments_delivery_id", table_name="payments")
    for column in ("delivery_id", "upi_amount", "cash_amount"):
        op.drop_column("payments", column)
