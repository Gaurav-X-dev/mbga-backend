"""Book online money only after merchant approval; restore existing pending balances.

Revision ID: 20261027_0060
Revises: 20261027_0059
"""
import sqlalchemy as sa
from alembic import op

revision = "20261027_0060"
down_revision = "20261027_0059"
branch_labels = None
depends_on = None

_PAYMENTS = sa.table("payments", sa.column("invoice_id"), sa.column("amount_collected"),
                     sa.column("cash_amount"), sa.column("mode"), sa.column("reconciliation_status"))
_INVOICES = sa.table("invoices", sa.column("id"), sa.column("paid_amount"),
                     sa.column("total_amount"), sa.column("balance"), sa.column("status"),
                     sa.column("updated_at"))
_PENDING = (
    sa.select(_PAYMENTS.c.invoice_id, sa.func.sum(
        _PAYMENTS.c.amount_collected - sa.case(
            (_PAYMENTS.c.mode == "SPLIT", sa.func.coalesce(_PAYMENTS.c.cash_amount, 0)), else_=0,
        )).label("amount"))
    .where(_PAYMENTS.c.reconciliation_status == "PENDING", _PAYMENTS.c.mode.in_(("UPI", "SPLIT")))
    .group_by(_PAYMENTS.c.invoice_id).subquery()
)


def _move_pending(direction: int) -> None:
    pending = sa.select(_PENDING.c.amount).where(_PENDING.c.invoice_id == _INVOICES.c.id).scalar_subquery()
    paid = _INVOICES.c.paid_amount + direction * pending
    # MySQL evaluates assignments left to right: paid_amount must be assigned last.
    op.execute(sa.update(_INVOICES).where(_INVOICES.c.id.in_(sa.select(_PENDING.c.invoice_id)))
               .ordered_values(
                   (_INVOICES.c.balance, _INVOICES.c.total_amount - paid),
                   (_INVOICES.c.status, sa.case((paid >= _INVOICES.c.total_amount, "PAID"),
                                              (paid > 0, "PARTIAL"), else_="UNPAID")),
                   (_INVOICES.c.updated_at, sa.func.current_timestamp()),
                   (_INVOICES.c.paid_amount, paid),
               ))


def upgrade() -> None:
    # Refuse an inconsistent legacy ledger before any DDL or balance changes.
    if not op.get_context().as_sql:
        inconsistent = op.get_bind().scalar(sa.select(sa.func.count()).select_from(
            _INVOICES.join(_PENDING, _PENDING.c.invoice_id == _INVOICES.c.id)
        ).where(sa.or_(_PENDING.c.amount > _INVOICES.c.paid_amount,
                       _INVOICES.c.paid_amount > _INVOICES.c.total_amount)))
        if inconsistent:
            raise RuntimeError("Pending payments exceed recorded invoice paid amounts; review ledger before migration.")
    op.add_column("payments", sa.Column("applied_amount", sa.BigInteger(), nullable=False, server_default="0"))
    op.execute("""
        UPDATE payments SET applied_amount = CASE
            WHEN reconciliation_status = 'INVALID' THEN
                CASE WHEN mode = 'SPLIT' THEN COALESCE(cash_amount, 0) ELSE 0 END
            ELSE amount_collected END
    """)
    _move_pending(-1)
    op.execute("""
        UPDATE payments SET applied_amount = CASE WHEN mode = 'SPLIT'
            THEN COALESCE(cash_amount, 0) ELSE 0 END
        WHERE reconciliation_status = 'PENDING' AND mode IN ('UPI', 'SPLIT')
    """)


def downgrade() -> None:
    _move_pending(1)
    op.drop_column("payments", "applied_amount")
