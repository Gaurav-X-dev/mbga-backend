"""Preserve existing app labels and quantity limits in the dynamic catalogue.

Revision ID: 20261015_0049
Revises: 20261015_0048

The catalogue remains administrator-managed.  This migration only repairs known built-in
seed values from earlier builds; it deliberately leaves custom administrator values alone.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261015_0049"
down_revision = "20261015_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    now = datetime.now(UTC)

    displays = {
        "LPG_5KG": ("5 KG Cylinder", "5 KG", ("5 KG", "5 KG LPG", "5 KG Cylinder")),
        "LPG_10KG": ("10 KG Cylinder", "10 KG", ("10 KG", "10 KG LPG", "10 KG Cylinder")),
        "LPG_19KG": ("19 KG Cylinder", "19 KG", ("19 KG", "19 KG Commercial", "19 KG Cylinder")),
        "LPG_47_5KG_L": (
            "47.5 KG Cylinder (Liquid)", "47.5 L",
            ("47.5 KG L", "47.5 KG LOT (Liquid)", "47.5 KG Cylinder (Liquid)"),
        ),
        "LPG_47_5KG_V": (
            "47.5 KG Cylinder (Vapour)", "47.5 V",
            ("47.5 KG V", "47.5 KG VOT (Vapor)", "47.5 KG Cylinder (Vapour)"),
        ),
        "LPG_422KG_HIPPO": ("422 KG Hippo", "422 Hippo", ("422 KG Hippo",)),
    }
    for code, (label, short_label, known_labels) in displays.items():
        placeholders = ", ".join(f":label_{index}" for index in range(len(known_labels)))
        parameters = {"code": code, "label": label, "short_label": short_label, "updated_at": now}
        parameters.update({f"label_{index}": value for index, value in enumerate(known_labels)})
        connection.execute(
            sa.text(
                "UPDATE cylinder_type_definitions "
                "SET label = :label, short_label = :short_label, updated_at = :updated_at "
                "WHERE code = :code AND is_protected = 1 "
                f"AND label IN ({placeholders}) "
                "AND (short_label IS NULL OR short_label IN "
                "('5 KG', '10 KG', '19 KG', '47.5 KG L', '47.5 KG V', "
                "'47.5 L', '47.5 V', '422 KG', '422 Hippo'))"
            ),
            parameters,
        )

    limits = {
        ("RETAIL", "LPG_5KG"): 100,
        ("RETAIL", "LPG_10KG"): 75,
        ("RETAIL", "LPG_19KG"): 50,
        ("INDUSTRIAL", "LPG_19KG"): 50,
        ("INDUSTRIAL", "LPG_47_5KG_L"): 30,
        ("INDUSTRIAL", "LPG_47_5KG_V"): 30,
        ("INDUSTRIAL", "LPG_422KG_HIPPO"): 5,
    }
    for (customer_type, cylinder_type), maximum in limits.items():
        connection.execute(
            sa.text(
                "UPDATE customer_type_cylinders "
                "SET max_quantity = :maximum, updated_at = :updated_at "
                "WHERE customer_type_code = :customer_type "
                "AND cylinder_type_code = :cylinder_type AND max_quantity IS NULL"
            ),
            {
                "customer_type": customer_type,
                "cylinder_type": cylinder_type,
                "maximum": maximum,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    # Data compatibility repair: reverting could overwrite valid administrator changes.
    pass
