import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.audit_logs.schemas import AuditLogCreate


def mask_mobile(mobile_number: str | None) -> str | None:
    """Keep only the last four digits, e.g. ``******3210``."""
    if not mobile_number:
        return None
    digits = "".join(ch for ch in mobile_number if ch.isdigit())
    return f"******{digits[-4:]}" if len(digits) >= 4 else "******"


def hash_device(device_id: str | None) -> str | None:
    return hashlib.sha256(device_id.encode("utf-8")).hexdigest() if device_id else None


class AuditLogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write_event(self, payload: AuditLogCreate) -> None:
        """Adds the event to the current transaction; the caller commits."""
        self.session.add(
            AuditLog(
                id=str(uuid4()),
                created_at=datetime.now(UTC),
                **payload.model_dump(),
            )
        )
