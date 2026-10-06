"""Open a rate for every cylinder type a live pricing month is missing.

`LPG_10KG` was added to the catalogue, but no price list ever showed it. A month opens by copying
the previous month's entries, so a type that did not exist last month gets no row this month -
and, having none this month, gets none next month either. A new type is invisible on every price
list for ever, which is what the merchants reported: 10 KG missing from the rate card, from the
per-customer override screen, and from the order form that prices against them.

The code that opens a month now tops up anything the default card knows and the month does not.
That fixes every month from here on. It cannot fix the months that are already open, and those
are the ones staff are working in today - so this adds the missing rows directly.

Rates come from the shipped default card, the same figures a merchant's very first month opens
with. That is a number staff change like any other rather than one they are stuck with; the
alternative is a cylinder that cannot be sold until somebody notices. Only `ACTIVE` and `DRAFT`
months are touched: an archived month is a record of what was charged, and adding a rate nobody
ever sold at would make it a worse one.

Revision ID: 20261006_0029
Revises: 20261006_0028
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0029"
down_revision = "20261006_0028"
branch_labels = None
depends_on = None

#: (cylinder_type, tier, bpcl_base_rate, tier_markup), matching DEFAULT_STANDARD_RATES.
DEFAULT_CARD = [
    ("LPG_5KG", "STANDARD", "445.00", "45.00"),
    ("LPG_10KG", "STANDARD", "890.00", "70.00"),
    ("LPG_19KG", "STANDARD", "1690.00", "110.00"),
    ("LPG_47_5KG_L", "STANDARD", "4225.00", "275.00"),
    ("LPG_47_5KG_V", "STANDARD", "4260.00", "275.00"),
    ("LPG_422KG_HIPPO", "STANDARD", "37550.00", "1450.00"),
]

# `customer_price` is a stored generated column - the database computes it from the two rates,
# and naming it here would be rejected.
_INSERT = sa.text(
    """
    INSERT INTO pricing_entries (pricing_month_id, cylinder_type, tier, bpcl_base_rate, tier_markup)
    SELECT m.id, :cylinder_type, :tier, :base, :markup
      FROM pricing_months m
     WHERE m.status IN ('ACTIVE', 'DRAFT')
       AND NOT EXISTS (
           SELECT 1 FROM pricing_entries e
            WHERE e.pricing_month_id = m.id
              AND e.cylinder_type = :cylinder_type
              AND e.tier = :tier
       )
    """
)


def upgrade() -> None:
    connection = op.get_bind()
    for cylinder_type, tier, base, markup in DEFAULT_CARD:
        connection.execute(
            _INSERT,
            {"cylinder_type": cylinder_type, "tier": tier, "base": base, "markup": markup},
        )


def downgrade() -> None:
    # Deliberately does nothing. The rows are indistinguishable from ones staff entered or
    # edited afterwards, and dropping a rate a merchant has been selling at - or that an order
    # was priced against - to undo a schema step would be the worse mistake.
    pass
