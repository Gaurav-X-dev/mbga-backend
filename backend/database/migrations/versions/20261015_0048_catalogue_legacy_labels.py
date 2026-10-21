"""Normalize legacy seed labels without overwriting custom admin labels.

Revision ID: 20261015_0048
Revises: 20261015_0047
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_0048"
down_revision = "20261015_0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    corrections = {
        "LPG_5KG": ("5 KG", "5 KG Cylinder"),
        "LPG_10KG": ("10 KG", "10 KG Cylinder"),
        "LPG_19KG": ("19 KG", "19 KG Cylinder"),
        "LPG_47_5KG_L": ("47.5 KG L", "47.5 KG Cylinder (Liquid)"),
        "LPG_47_5KG_V": ("47.5 KG V", "47.5 KG Cylinder (Vapour)"),
    }
    for code, (label, legacy_label) in corrections.items():
        connection.execute(
            sa.text(
                "UPDATE cylinder_type_definitions SET label = :label "
                "WHERE code = :code AND is_protected = 1 AND label = :legacy_label"
            ),
            {"code": code, "label": label, "legacy_label": legacy_label},
        )


def downgrade() -> None:
    pass
