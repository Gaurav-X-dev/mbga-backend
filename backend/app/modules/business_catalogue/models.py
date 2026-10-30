from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class CustomerTypeDefinition(Base):
    __tablename__ = "customer_type_definitions"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_prefix: Mapped[str] = mapped_column(String(8), default="C", server_default="C")
    requires_delivery_sites: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    requires_gst_invoice: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)


class CylinderTypeDefinition(Base):
    __tablename__ = "cylinder_type_definitions"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    short_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    variant: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hsn_sac: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), default="PCS", server_default="PCS")
    default_base_rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    default_markup: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, server_default="0")
    gst_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=18, server_default="18")
    reorder_threshold: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)


class CustomerTypeCylinder(Base):
    __tablename__ = "customer_type_cylinders"
    __table_args__ = (UniqueConstraint("customer_type_code", "cylinder_type_code", name="uq_customer_type_cylinder"),)

    customer_type_code: Mapped[str] = mapped_column(
        ForeignKey("customer_type_definitions.code"), primary_key=True
    )
    cylinder_type_code: Mapped[str] = mapped_column(
        ForeignKey("cylinder_type_definitions.code"), primary_key=True
    )
    min_quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    max_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class KycDocumentTypeDefinition(Base):
    __tablename__ = "kyc_document_type_definitions"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    number_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    min_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiry_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    scan_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class CustomerTypeKycRule(Base):
    __tablename__ = "customer_type_kyc_rules"
    __table_args__ = (UniqueConstraint("customer_type_code", "document_type_code", name="uq_customer_type_kyc_rule"),)

    customer_type_code: Mapped[str] = mapped_column(
        ForeignKey("customer_type_definitions.code"), primary_key=True
    )
    document_type_code: Mapped[str] = mapped_column(
        ForeignKey("kyc_document_type_definitions.code"), primary_key=True
    )
    requirement_mode: Mapped[str] = mapped_column(String(20))
    requirement_group: Mapped[str | None] = mapped_column(String(60), nullable=True)
    min_required: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
