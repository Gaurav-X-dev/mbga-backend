"""Dynamic customer, cylinder and KYC business catalogue.

Revision ID: 20261015_0045
Revises: 20261013_0044
"""
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20261015_0045"
down_revision = "20261013_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_type_definitions",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.Column("updated_by_name", sa.String(160), nullable=True),
    )
    op.create_table(
        "cylinder_type_definitions",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("short_label", sa.String(80), nullable=True),
        sa.Column("weight_kg", sa.Numeric(8, 2), nullable=False),
        sa.Column("variant", sa.String(40), nullable=True),
        sa.Column("hsn_sac", sa.String(20), nullable=True),
        sa.Column("unit", sa.String(20), nullable=False, server_default="PCS"),
        sa.Column("default_base_rate", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("default_markup", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("gst_percent", sa.Numeric(5, 2), nullable=False, server_default="18"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.Column("updated_by_name", sa.String(160), nullable=True),
    )
    op.create_table(
        "kyc_document_type_definitions",
        sa.Column("code", sa.String(40), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("number_pattern", sa.String(255), nullable=True),
        sa.Column("min_length", sa.Integer(), nullable=True),
        sa.Column("max_length", sa.Integer(), nullable=True),
        sa.Column("expiry_required", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("scan_required", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
    )
    op.create_table(
        "customer_type_cylinders",
        sa.Column("customer_type_code", sa.String(40), sa.ForeignKey("customer_type_definitions.code"), primary_key=True),
        sa.Column("cylinder_type_code", sa.String(40), sa.ForeignKey("cylinder_type_definitions.code"), primary_key=True),
        sa.Column("min_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_quantity", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("customer_type_code", "cylinder_type_code", name="uq_customer_type_cylinder"),
    )
    op.create_table(
        "customer_type_kyc_rules",
        sa.Column("customer_type_code", sa.String(40), sa.ForeignKey("customer_type_definitions.code"), primary_key=True),
        sa.Column("document_type_code", sa.String(40), sa.ForeignKey("kyc_document_type_definitions.code"), primary_key=True),
        sa.Column("requirement_mode", sa.String(20), nullable=False),
        sa.Column("requirement_group", sa.String(60), nullable=True),
        sa.Column("min_required", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("customer_type_code", "document_type_code", name="uq_customer_type_kyc_rule"),
    )

    now = datetime.now(UTC)
    customer_types = sa.table("customer_type_definitions", sa.column("code"), sa.column("label"), sa.column("description"),
        sa.column("is_active"), sa.column("is_protected"), sa.column("sort_order"), sa.column("created_at"), sa.column("updated_at"))
    op.bulk_insert(customer_types, [
        {"code": "RETAIL", "label": "Retail", "description": "Retail LPG customer", "is_active": True, "is_protected": True, "sort_order": 10, "created_at": now, "updated_at": now},
        {"code": "INDUSTRIAL", "label": "Industrial", "description": "Industrial LPG customer", "is_active": True, "is_protected": True, "sort_order": 20, "created_at": now, "updated_at": now},
    ])
    cylinders = sa.table("cylinder_type_definitions", sa.column("code"), sa.column("label"), sa.column("short_label"),
        sa.column("weight_kg"), sa.column("variant"), sa.column("hsn_sac"), sa.column("unit"),
        sa.column("default_base_rate"), sa.column("default_markup"), sa.column("gst_percent"), sa.column("reorder_threshold"),
        sa.column("is_active"), sa.column("is_protected"), sa.column("sort_order"), sa.column("created_at"), sa.column("updated_at"))
    cylinder_rows = [
        ("LPG_5KG", "5 KG Cylinder", "5 KG", "5.00", None, "445.00", "45.00", 150),
        ("LPG_10KG", "10 KG Cylinder", "10 KG", "10.00", None, "1200.00", "110.00", 0),
        ("LPG_19KG", "19 KG Cylinder", "19 KG", "19.00", None, "1690.00", "110.00", 120),
        ("LPG_47_5KG_L", "47.5 KG Cylinder (Liquid)", "47.5 L", "47.50", "LIQUID", "4225.00", "275.00", 50),
        ("LPG_47_5KG_V", "47.5 KG Cylinder (Vapour)", "47.5 V", "47.50", "VAPOUR", "4260.00", "275.00", 40),
        ("LPG_422KG_HIPPO", "422 KG Hippo", "422 KG", "422.00", "HIPPO", "37550.00", "1450.00", 4),
    ]
    op.bulk_insert(cylinders, [{"code": r[0], "label": r[1], "short_label": r[2], "weight_kg": r[3], "variant": r[4],
        "hsn_sac": "271119", "unit": "PCS", "default_base_rate": r[5], "default_markup": r[6], "gst_percent": "18.00",
        "reorder_threshold": r[7], "is_active": True, "is_protected": True, "sort_order": (i + 1) * 10,
        "created_at": now, "updated_at": now} for i, r in enumerate(cylinder_rows)])
    docs = sa.table("kyc_document_type_definitions", sa.column("code"), sa.column("label"), sa.column("number_pattern"),
        sa.column("min_length"), sa.column("max_length"), sa.column("expiry_required"), sa.column("scan_required"),
        sa.column("is_active"), sa.column("is_protected"), sa.column("sort_order"), sa.column("created_at"), sa.column("updated_at"))
    op.bulk_insert(docs, [
        {"code": "AADHAAR", "label": "Aadhaar Card", "number_pattern": r"^[0-9]{12}$", "min_length": 12, "max_length": 12, "expiry_required": False, "scan_required": True, "is_active": True, "is_protected": True, "sort_order": 10, "created_at": now, "updated_at": now},
        {"code": "PAN", "label": "PAN Card", "number_pattern": r"^[A-Z]{5}[0-9]{4}[A-Z]$", "min_length": 10, "max_length": 10, "expiry_required": False, "scan_required": True, "is_active": True, "is_protected": True, "sort_order": 20, "created_at": now, "updated_at": now},
        {"code": "GST", "label": "GST Certificate", "number_pattern": r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", "min_length": 15, "max_length": 15, "expiry_required": False, "scan_required": True, "is_active": True, "is_protected": True, "sort_order": 30, "created_at": now, "updated_at": now},
        {"code": "FSSAI", "label": "FSSAI Certificate", "number_pattern": r"^[0-9]{14}$", "min_length": 14, "max_length": 14, "expiry_required": True, "scan_required": True, "is_active": True, "is_protected": True, "sort_order": 40, "created_at": now, "updated_at": now},
        {"code": "MSME", "label": "MSME / Udyam Certificate", "number_pattern": r"^UDYAM-[A-Z]{2}-[0-9]{2}-[0-9]{7}$", "min_length": 19, "max_length": 19, "expiry_required": False, "scan_required": True, "is_active": True, "is_protected": True, "sort_order": 50, "created_at": now, "updated_at": now},
    ])
    mapping = sa.table("customer_type_cylinders", sa.column("customer_type_code"), sa.column("cylinder_type_code"),
        sa.column("min_quantity"), sa.column("max_quantity"), sa.column("sort_order"), sa.column("is_active"), sa.column("updated_at"))
    retail = [("LPG_5KG", 100), ("LPG_10KG", 75), ("LPG_19KG", 50)]
    industrial = [("LPG_19KG", 50), ("LPG_47_5KG_L", 30), ("LPG_47_5KG_V", 30), ("LPG_422KG_HIPPO", 5)]
    op.bulk_insert(mapping, [{"customer_type_code": ct, "cylinder_type_code": row[0], "min_quantity": 1,
        "max_quantity": row[1],
        "sort_order": (i + 1) * 10, "is_active": True, "updated_at": now}
        for ct, values in (("RETAIL", retail), ("INDUSTRIAL", industrial)) for i, row in enumerate(values)])
    rules = sa.table("customer_type_kyc_rules", sa.column("customer_type_code"), sa.column("document_type_code"),
        sa.column("requirement_mode"), sa.column("requirement_group"), sa.column("min_required"), sa.column("is_active"),
        sa.column("sort_order"), sa.column("updated_at"))
    retail_rules = [(x, "ANY_OF", "RETAIL_PRIMARY", 1) for x in ("AADHAAR", "GST", "FSSAI", "PAN")]
    industrial_rules = [("GST", "REQUIRED", None, 1), ("PAN", "REQUIRED", None, 1),
        ("FSSAI", "OPTIONAL", None, 1), ("AADHAAR", "OPTIONAL", None, 1), ("MSME", "OPTIONAL", None, 1)]
    op.bulk_insert(rules, [{"customer_type_code": ct, "document_type_code": r[0], "requirement_mode": r[1],
        "requirement_group": r[2], "min_required": r[3], "is_active": True, "sort_order": (i + 1) * 10, "updated_at": now}
        for ct, values in (("RETAIL", retail_rules), ("INDUSTRIAL", industrial_rules)) for i, r in enumerate(values)])


def downgrade() -> None:
    op.drop_table("customer_type_kyc_rules")
    op.drop_table("customer_type_cylinders")
    op.drop_table("kyc_document_type_definitions")
    op.drop_table("cylinder_type_definitions")
    op.drop_table("customer_type_definitions")
