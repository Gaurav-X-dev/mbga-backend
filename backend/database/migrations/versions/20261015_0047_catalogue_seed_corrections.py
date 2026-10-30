"""Correct catalogue defaults shipped by the early 0045 build.

Revision ID: 20261015_0047
Revises: 20261015_0046

Only protected built-in rows are touched.  Custom rows created from the admin panel and
subsequent administrator edits remain intact.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0047"
down_revision = "20261015_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    corrections = {
        "LPG_5KG": ("5 KG", 150),
        "LPG_10KG": ("10 KG", 0),
        "LPG_19KG": ("19 KG", 120),
        "LPG_47_5KG_L": ("47.5 KG L", 50),
        "LPG_47_5KG_V": ("47.5 KG V", 40),
        "LPG_422KG_HIPPO": ("422 KG Hippo", 4),
    }
    old_seed_labels = {
        "LPG_5KG": "5 KG LPG",
        "LPG_10KG": "10 KG LPG",
        "LPG_19KG": "19 KG Commercial",
        "LPG_47_5KG_L": "47.5 KG LOT (Liquid)",
        "LPG_47_5KG_V": "47.5 KG VOT (Vapor)",
        "LPG_422KG_HIPPO": "422 KG Hippo",
    }
    for code, (label, threshold) in corrections.items():
        # Replace only known seed values, so an administrator's custom label survives.
        connection.execute(
            sa.text(
                "UPDATE cylinder_type_definitions "
                "SET label = :label "
                "WHERE code = :code AND is_protected = 1 AND label = :old_label"
            ),
            {"code": code, "label": label, "old_label": old_seed_labels[code]},
        )
        # The early build seeded every threshold as zero.  A non-zero value is an admin edit.
        if threshold:
            connection.execute(
                sa.text(
                    "UPDATE cylinder_type_definitions "
                    "SET reorder_threshold = :threshold "
                    "WHERE code = :code AND is_protected = 1 AND reorder_threshold = 0"
                ),
                {"code": code, "threshold": threshold},
            )


def downgrade() -> None:
    # This is a data correction. Reverting it could destroy valid administrator settings.
    pass
