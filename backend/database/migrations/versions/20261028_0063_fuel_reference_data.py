"""Database-owned fuel type reference data, seeded once without expense changes."""
from alembic import op
import sqlalchemy as sa
revision="20261028_0063"
down_revision="20261028_0062"
branch_labels=None
depends_on=None


def upgrade():
    table=op.create_table("expense_fuel_types",
        sa.Column("code",sa.String(20),primary_key=True),
        sa.Column("label",sa.String(60),nullable=False),
        sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.Column("sort_order",sa.Integer(),nullable=False,server_default="0"))
    # Initial reference data; runtime dropdowns and validation always read this table.
    op.bulk_insert(table,[{"code":"DIESEL","label":"Diesel","is_active":True,"sort_order":0},
        {"code":"PETROL","label":"Petrol","is_active":True,"sort_order":1},
        {"code":"CNG","label":"CNG","is_active":True,"sort_order":2}])


def downgrade():
    op.drop_table("expense_fuel_types")
