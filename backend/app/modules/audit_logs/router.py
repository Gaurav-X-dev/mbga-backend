from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.audit_logs.schemas import AuditLogListResponse, AuditLogResponse
from app.modules.roles.permissions import AUDIT_LOG_VIEW
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session

router = APIRouter(prefix="/audit-logs", tags=["admin-audit-logs"])


@router.get("", response_model=AuditLogListResponse, dependencies=[Depends(require_permission(AUDIT_LOG_VIEW))])
async def list_audit_logs(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor_user_id: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditLogListResponse:
    filters = []
    if actor_user_id:
        filters.append(AuditLog.actor_user_id == actor_user_id)
    if action:
        filters.append(AuditLog.event_type == action)
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(AuditLog.entity_id == entity_id)
    if date_from:
        filters.append(AuditLog.created_at >= date_from)
    if date_to:
        filters.append(AuditLog.created_at <= date_to)
    offset = (page - 1) * page_size
    total = int(await session.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0)
    result = await session.execute(
        select(AuditLog).where(*filters).order_by(AuditLog.created_at.desc(), AuditLog.id).limit(page_size).offset(offset)
    )
    items = [AuditLogResponse.model_validate(log, from_attributes=True) for log in result.scalars().all()]
    return AuditLogListResponse(items=items, page=page, page_size=page_size, total=total, total_pages=(total + page_size - 1) // page_size)


@router.get("/{audit_log_id}", response_model=AuditLogResponse, dependencies=[Depends(require_permission(AUDIT_LOG_VIEW))])
async def get_audit_log(audit_log_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> AuditLogResponse:
    log = await session.get(AuditLog, audit_log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return AuditLogResponse.model_validate(log, from_attributes=True)
