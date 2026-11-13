"""One-level owner/branch links and retained legacy access audit records."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class CustomerBrand(Base):
    __tablename__ = "customer_brands"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    owner_customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customer_profiles.id"), nullable=True, unique=True
    )


class CustomerOutlet(Base):
    __tablename__ = "customer_brand_outlets"
    customer_id: Mapped[str] = mapped_column(ForeignKey("customer_profiles.id"), primary_key=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("customer_brands.id"), index=True)
    permissions: Mapped[str | None] = mapped_column(Text, nullable=True)


class CustomerAccessRole(Base):
    """Historical only: no role-management endpoint or authorization use remains."""

    __tablename__ = "customer_access_roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    permissions: Mapped[str] = mapped_column(Text)


class CustomerMembership(Base):
    """Historical only: legacy access was revoked by migration 0077."""

    __tablename__ = "customer_memberships"
    __table_args__ = (
        UniqueConstraint("scope_id", "mobile_number", name="uq_customer_membership_phone"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    # A scope is either a brand or one outlet; target type is explicitly stored.
    scope_id: Mapped[str] = mapped_column(String(36), index=True)
    scope_type: Mapped[str] = mapped_column(String(10))
    mobile_number: Mapped[str] = mapped_column(String(15), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("customer_access_roles.id"))
    status: Mapped[str] = mapped_column(String(12))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CustomerTeamMember(Base):
    """Direct owner-authorized employee access; scope IDs remain for audit after removal."""

    __tablename__ = "customer_team_members"
    __table_args__ = (
        UniqueConstraint(
            "owner_customer_id", "user_id", "scope_type", "scope_id", name="uq_customer_team_scope"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(ForeignKey("merchants.id"), index=True)
    owner_customer_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    mobile_number: Mapped[str] = mapped_column(String(20))
    scope_type: Mapped[str] = mapped_column(String(10))
    scope_id: Mapped[str] = mapped_column(String(36), index=True)
    preset: Mapped[str] = mapped_column(String(20))
    permissions: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), index=True)
    created_by: Mapped[str] = mapped_column(String(36))
    updated_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
