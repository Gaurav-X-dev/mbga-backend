from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    __table_args__ = (
        Index("ix_customer_profiles_merchant_status", "merchant_id", "status"),
        Index("ix_customer_profiles_mobile", "mobile_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Display code (MBGA-R-0001). Unique, but never used for authorisation - `id` is.
    code: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(ForeignKey("merchants.id"), nullable=True, index=True)
    merchant_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    customer_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mobile_number: Mapped[str] = mapped_column(String(20), unique=True)
    # `name` is the business name; the mobile contract calls it `businessName`.
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gst_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pricing_tier: Mapped[str] = mapped_column(String(30), default="STANDARD", server_default="STANDARD")
    # Registered / primary delivery address, stored as columns so a report can group on city.
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address_pincode: Mapped[str | None] = mapped_column(String(6), nullable=True)
    # The account workflow status. `kyc_status` tracks document verification separately
    # because the spec exposes them as two independent fields the apps route on.
    status: Mapped[str] = mapped_column(String(40), index=True)
    kyc_status: Mapped[str] = mapped_column(String(30), default="NOT_SUBMITTED", server_default="NOT_SUBMITTED", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    mobile_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerDocument(Base):
    __tablename__ = "customer_documents"
    __table_args__ = (
        Index("ix_customer_documents_customer_status", "customer_id", "status"),
        Index("ix_customer_documents_owner_type", "owner_user_id", "document_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # The opaque handle the apps use. Generated server-side; never guessable, never a path.
    file_id: Mapped[str | None] = mapped_column(String(60), unique=True, nullable=True)
    # Nullable because an upload is staged before the customer profile exists: during
    # self-registration the file is bound to the onboarding user first and linked on submit.
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customer_profiles.id"), nullable=True, index=True)
    # Who may attach this upload. Both are set at upload time and never move afterwards.
    owner_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    # Superseded by the encrypted column below; retained so existing rows still read.
    document_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    number_masked: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Keyed HMAC, not a plain digest - these identifiers have too little entropy for one.
    number_lookup_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scan_status: Mapped[str] = mapped_column(String(20), default="SKIPPED", server_default="SKIPPED")
    storage_provider: Mapped[str] = mapped_column(String(30), default="local", server_default="local")
    # Set when the upload is attached to a registration; a finalized file cannot be reused.
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(180))
    mime_type: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer)
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerDeliverySite(Base):
    """An industrial customer's delivery location (spec 3.5).

    Retail customers have none; the response returns an empty list for them. Exactly one row
    per customer carries `is_primary`, which the registration service enforces.
    """

    __tablename__ = "customer_delivery_sites"
    __table_args__ = (
        Index("ix_customer_delivery_sites_customer_primary", "customer_id", "is_primary"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    address_line1: Mapped[str] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str] = mapped_column(String(120))
    address_state: Mapped[str] = mapped_column(String(120))
    address_pincode: Mapped[str] = mapped_column(String(6))
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    contact_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KycApplication(Base):
    """One review cycle for a customer (spec 3.7).

    A separate table rather than more columns on the profile, for two reasons the mobile
    contract forces: the app addresses an application by its own stable id, and a rejected
    customer may correct and resubmit - which creates a second application while the first
    stays on record for the audit trail.
    """

    __tablename__ = "kyc_applications"
    __table_args__ = (
        Index("ix_kyc_applications_merchant_status", "merchant_id", "status", "submitted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The reviewer's display name at decision time, so a later rename does not rewrite history.
    reviewed_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerCodeSequence(Base):
    """Concurrency-safe counter behind `MBGA-R-0001`.

    One row per prefix, incremented under `SELECT ... FOR UPDATE`. A `MAX(code) + 1` scan
    would hand the same number to two concurrent registrations, and the unique index would
    then fail one of them at random.
    """

    __tablename__ = "customer_code_sequences"

    prefix: Mapped[str] = mapped_column(String(20), primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
