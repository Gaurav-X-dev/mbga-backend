"""Record what the driver actually handed over, beside what the van was loaded with.

`delivery_slip_items.quantity` is what the office allocated to the slip. Until now it was also
what came off the godown's books at handover, because the ledger had nothing else to read - so a
driver who handed over two of four cylinders still took four off the shelf, while two were
physically still on his van. The count went wrong silently, with no movement row to explain it.

`delivered_quantity` is the driver's own figure, recorded when he confirms the counts at the gate.
It is deliberately a **second** column rather than an overwrite of `quantity`: the allocation is
what the van is answerable for, and `_committed()` subtracts it from the godown's free stock while
the slip is out. Overwriting it would make a part-delivered van look like it had been loaded
lighter than it was, and a second van could then be loaded from cylinders the first is carrying.

**NULL means "nothing was recorded"**, and the ledger then books the full allocation exactly as
before. That is what keeps this migration safe: the merchant channel's own confirmation endpoint
never sets it, so every existing slip and every office-confirmed handover behaves unchanged.

Revision ID: 20261001_0024
Revises: 20260929_0023
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0024"
down_revision = "20260929_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no server default: an existing row has no driver-recorded figure, and filling
    # one in from `quantity` would be inventing evidence that the handover was complete.
    op.add_column(
        "delivery_slip_items",
        sa.Column("delivered_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # The driver's counts are lost, and the ledger goes back to booking the whole allocation.
    op.drop_column("delivery_slip_items", "delivered_quantity")
