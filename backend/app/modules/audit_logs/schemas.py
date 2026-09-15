from datetime import datetime

from pydantic import BaseModel


class AuditLogCreate(BaseModel):
    event_type: str
    actor_user_id: str | None = None


class AuditLogResponse(BaseModel):
    id: str
    event_type: str
    actor_user_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    message: str | None = None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
