from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

PROCESSING = "PROCESSING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"


class IdempotencyKey(Base):
    """One retry-sensitive operation, remembered so a repeat returns the first result.

    The unique constraint is the whole mechanism: two concurrent identical requests race to
    insert the same (actor, merchant, operation, key) row, exactly one wins, and the loser
    waits for or replays the winner's result. Scoping by actor and merchant means two
    tenants can use the same key string without colliding.

    Nothing sensitive is stored: `request_fingerprint` is a SHA-256 of the canonical body,
    never the body itself, so tokens, OTPs and KYC identifiers cannot land here.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("actor_user_id", "merchant_id", "operation", "idempotency_key", name="uq_idempotency_scope_key"),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
        Index("ix_idempotency_keys_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Actor scope. merchant_id is empty-string rather than NULL so the unique constraint
    # still matches for customer actors — MySQL treats NULLs as distinct.
    actor_user_id: Mapped[str] = mapped_column(String(36), index=True)
    merchant_id: Mapped[str] = mapped_column(String(36), default="")
    operation: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default=PROCESSING)
    # Result of the first successful attempt, replayed verbatim on a retry.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set instead of a body when the result is a row the caller re-reads.
    result_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
