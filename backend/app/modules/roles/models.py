from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.database.base import Base


class RoleType(StrEnum):
    SYSTEM = "system"
    CUSTOM = "custom"


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        Index("ix_roles_active_code", "is_active", "code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    role_type: Mapped[str] = mapped_column(String(20), default=RoleType.CUSTOM)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
    login_channels = relationship("RoleLoginChannel", back_populates="role", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
        Index("ix_role_permissions_role_id", "role_id"),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), primary_key=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    role = relationship("Role", back_populates="permissions")


class RoleLoginChannel(Base):
    __tablename__ = "role_login_channels"
    __table_args__ = (
        UniqueConstraint("role_id", "login_channel", name="uq_role_login_channel"),
        Index("ix_role_login_channels_role_channel_allowed", "role_id", "login_channel", "is_allowed"),
    )

    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), primary_key=True)
    login_channel: Mapped[str] = mapped_column(String(30), primary_key=True)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    role = relationship("Role", back_populates="login_channels")
