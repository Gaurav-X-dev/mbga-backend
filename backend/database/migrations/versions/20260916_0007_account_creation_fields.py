"""account creation fields

Revision ID: 20260916_0007
Revises: 20260914_0006
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260916_0007"
down_revision = "20260914_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("merchants", sa.Column("contact_person_name", sa.String(length=160), nullable=True))
    op.add_column("merchants", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("merchants", sa.Column("gst_number", sa.String(length=30), nullable=True))
    op.add_column("merchants", sa.Column("address_line_1", sa.String(length=255), nullable=True))
    op.add_column("merchants", sa.Column("address_line_2", sa.String(length=255), nullable=True))
    op.add_column("merchants", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("merchants", sa.Column("state", sa.String(length=120), nullable=True))
    op.add_column("merchants", sa.Column("postal_code", sa.String(length=20), nullable=True))
    op.create_index("ix_merchants_email", "merchants", ["email"], unique=True)
    op.create_index("ix_merchants_city_state", "merchants", ["city", "state"])

    op.add_column("delivery_profiles", sa.Column("employee_code", sa.String(length=80), nullable=True))
    op.add_column("delivery_profiles", sa.Column("driving_license_number", sa.String(length=80), nullable=True))
    op.add_column("delivery_profiles", sa.Column("driving_license_expiry", sa.DateTime(), nullable=True))
    op.add_column("delivery_profiles", sa.Column("address", sa.String(length=255), nullable=True))
    op.create_index("ix_delivery_profiles_employee_code", "delivery_profiles", ["employee_code"])
    op.create_unique_constraint(
        "uq_delivery_profiles_merchant_employee_code",
        "delivery_profiles",
        ["merchant_id", "employee_code"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_delivery_profiles_merchant_employee_code", "delivery_profiles", type_="unique")
    op.drop_index("ix_delivery_profiles_employee_code", table_name="delivery_profiles")
    op.drop_column("delivery_profiles", "address")
    op.drop_column("delivery_profiles", "driving_license_expiry")
    op.drop_column("delivery_profiles", "driving_license_number")
    op.drop_column("delivery_profiles", "employee_code")

    op.drop_index("ix_merchants_city_state", table_name="merchants")
    op.drop_index("ix_merchants_email", table_name="merchants")
    op.drop_column("merchants", "postal_code")
    op.drop_column("merchants", "state")
    op.drop_column("merchants", "city")
    op.drop_column("merchants", "address_line_2")
    op.drop_column("merchants", "address_line_1")
    op.drop_column("merchants", "gst_number")
    op.drop_column("merchants", "email")
    op.drop_column("merchants", "contact_person_name")
