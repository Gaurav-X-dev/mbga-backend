from app.modules.audit_logs.schemas import AuditLogCreate


class AuditLogService:
    async def write_event(self, payload: AuditLogCreate) -> None:
        # TODO: Persist audit event after audit model review.
        return None
