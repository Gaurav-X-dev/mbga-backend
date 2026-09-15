from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role
from app.modules.authentication.models import LoginSession
from app.modules.users.models import User
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session

router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])


@router.get("/summary", dependencies=[Depends(require_permission("dashboard.view"))])
async def dashboard_summary(session: Annotated[AsyncSession, Depends(get_db_session)]) -> dict[str, int]:
    async def count(model: type) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    active_users = await session.scalar(select(func.count()).select_from(User).where(User.status == "ACTIVE"))
    active_roles = await session.scalar(select(func.count()).select_from(Role).where(Role.is_active.is_(True)))
    active_permissions = await session.scalar(
        select(func.count()).select_from(Permission).where(Permission.is_active.is_(True))
    )
    blocked_users = await session.scalar(select(func.count()).select_from(User).where(User.status == "BLOCKED"))
    active_sessions = await session.scalar(
        select(func.count()).select_from(LoginSession).where(LoginSession.revoked_at.is_(None))
    )
    return {
        "users": await count(User),
        "active_users": int(active_users or 0),
        "blocked_users": int(blocked_users or 0),
        "roles": await count(Role),
        "active_roles": int(active_roles or 0),
        "permissions": await count(Permission),
        "active_permissions": int(active_permissions or 0),
        "active_sessions": int(active_sessions or 0),
        "audit_logs": await count(AuditLog),
    }
