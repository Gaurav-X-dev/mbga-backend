from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor_user_id", "actor_user_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Authentication events only. Never store codes, tokens or full mobile numbers here.
    login_channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    masked_mobile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
