from sqlalchemy.ext.asyncio import AsyncSession


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
