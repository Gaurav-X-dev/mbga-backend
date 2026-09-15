from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.constants import LoginChannel
from app.modules.permissions.models import Permission
from app.modules.permissions.schemas import PermissionResponse
from app.modules.roles.models import Role, RoleLoginChannel, RolePermission
from app.modules.roles.permissions import (
    ROLE_ACTIVATE,
    ROLE_ASSIGN_CHANNELS,
    ROLE_ASSIGN_PERMISSIONS,
    ROLE_CREATE,
    ROLE_DELETE,
    ROLE_UPDATE,
    ROLE_VIEW,
)
from app.modules.roles.repository import RoleRepository
from app.modules.roles.schemas import (
    RoleChannelListAssignment,
    RoleCreate,
    RoleListResponse,
    RolePermissionAssignment,
    RoleResponse,
    RoleUpdate,
)
from app.modules.roles.service import RoleService
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.modules.users.schemas import UserSummary
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session

router = APIRouter()


def get_role_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> RoleService:
    return RoleService(RoleRepository(session))


async def _audit(session: AsyncSession, event_type: str, entity_id: str, message: str) -> None:
    if not hasattr(session, "add"):
        return
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type=event_type,
            actor_user_id=None,
            entity_type="role",
            entity_id=entity_id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission(ROLE_CREATE))])
async def create_role(payload: RoleCreate, service: Annotated[RoleService, Depends(get_role_service)]) -> RoleResponse:
    role = await service.create_role(payload)
    await _audit(service.repository.session, "role.created", role.id, "Role created")
    await service.repository.session.commit()
    return RoleResponse.model_validate(role, from_attributes=True)


@router.get("/roles", response_model=RoleListResponse, dependencies=[Depends(require_permission(ROLE_VIEW))])
async def list_roles(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    search: str | None = None,
    is_active: bool | None = None,
    is_system: bool | None = None,
    login_channel: LoginChannel | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RoleListResponse:
    filters = []
    if search:
        like = f"%{search.lower()}%"
        filters.append(func.lower(Role.code).like(like) | func.lower(Role.name).like(like))
    if is_active is not None:
        filters.append(Role.is_active.is_(is_active))
    if is_system is not None:
        filters.append(Role.is_system.is_(is_system))
    stmt = select(Role).where(*filters)
    count_stmt = select(func.count()).select_from(Role).where(*filters)
    if login_channel is not None:
        stmt = stmt.join(RoleLoginChannel, RoleLoginChannel.role_id == Role.id).where(
            RoleLoginChannel.login_channel == login_channel.value,
            RoleLoginChannel.is_allowed.is_(True),
        )
        count_stmt = count_stmt.join(RoleLoginChannel, RoleLoginChannel.role_id == Role.id).where(
            RoleLoginChannel.login_channel == login_channel.value,
            RoleLoginChannel.is_allowed.is_(True),
        )
    offset = (page - 1) * page_size
    result = await session.execute(stmt.order_by(Role.code).limit(page_size).offset(offset))
    total = int(await session.scalar(count_stmt) or 0)
    return RoleListResponse(
        items=[RoleResponse.model_validate(role, from_attributes=True) for role in result.scalars().all()],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/roles/{role_id}", response_model=RoleResponse, dependencies=[Depends(require_permission(ROLE_VIEW))])
async def get_role(role_id: str, service: Annotated[RoleService, Depends(get_role_service)]) -> RoleResponse:
    role = await service.repository.get_role(role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return RoleResponse.model_validate(role, from_attributes=True)


@router.patch("/roles/{role_id}", response_model=RoleResponse, dependencies=[Depends(require_permission(ROLE_UPDATE))])
async def update_role(
    role_id: str,
    payload: RoleUpdate,
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleResponse:
    role = await service.update_role(role_id, payload)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    await _audit(service.repository.session, "role.updated", role.id, "Role updated")
    await service.repository.session.commit()
    return RoleResponse.model_validate(role, from_attributes=True)


@router.delete("/roles/{role_id}", status_code=204, dependencies=[Depends(require_permission(ROLE_DELETE))])
async def delete_role(role_id: str, service: Annotated[RoleService, Depends(get_role_service)]) -> None:
    role = await service.repository.get_role(role_id)
    if role and role.code == "super_admin":
        await _audit(service.repository.session, "role.protected_rejected", role_id, "Cannot delete super_admin role")
        await service.repository.session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin role is protected")
    await service.delete_role(role_id)
    await _audit(service.repository.session, "role.deleted", role_id, "Role deleted")
    await service.repository.session.commit()


@router.post("/roles/{role_id}/activate", response_model=RoleResponse, dependencies=[Depends(require_permission(ROLE_ACTIVATE))])
async def activate_role(role_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> RoleResponse:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    role.is_active = True
    role.updated_at = datetime.now(UTC)
    await _audit(session, "role.activated", role.id, "Role activated")
    await session.commit()
    return RoleResponse.model_validate(role, from_attributes=True)


@router.post("/roles/{role_id}/deactivate", response_model=RoleResponse, dependencies=[Depends(require_permission(ROLE_ACTIVATE))])
async def deactivate_role(role_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> RoleResponse:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.code == "super_admin":
        await _audit(session, "role.protected_rejected", role.id, "Cannot deactivate super_admin role")
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin role is protected")
    role.is_active = False
    role.updated_at = datetime.now(UTC)
    await _audit(session, "role.deactivated", role.id, "Role deactivated")
    await session.commit()
    return RoleResponse.model_validate(role, from_attributes=True)


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionResponse], dependencies=[Depends(require_permission(ROLE_VIEW))])
async def list_role_permissions(role_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[PermissionResponse]:
    result = await session.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.module, Permission.action, Permission.code)
    )
    return [PermissionResponse.model_validate(permission, from_attributes=True) for permission in result.scalars().all()]


@router.put("/roles/{role_id}/permissions", status_code=204, dependencies=[Depends(require_permission(ROLE_ASSIGN_PERMISSIONS))])
async def replace_role_permissions(
    role_id: str,
    payload: RolePermissionAssignment,
    service: Annotated[RoleService, Depends(get_role_service)],
) -> None:
    role = await service.repository.get_role(role_id)
    if role and role.code == "super_admin":
        await _audit(service.repository.session, "role.protected_rejected", role_id, "Cannot replace Super Admin permissions")
        await service.repository.session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin permissions are protected")
    await service.replace_permissions(role_id, payload.permission_ids)
    await _audit(service.repository.session, "role.permissions_replaced", role_id, "Role permissions replaced")
    await service.repository.session.commit()


@router.post("/roles/{role_id}/permissions/{permission_id}", status_code=204, dependencies=[Depends(require_permission(ROLE_ASSIGN_PERMISSIONS))])
async def add_role_permission(
    role_id: str,
    permission_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    role = await session.get(Role, role_id)
    permission = await session.get(Permission, permission_id)
    if role is None or permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role or permission not found")
    existing = await session.get(RolePermission, {"role_id": role_id, "permission_id": permission_id})
    if existing is None:
        session.add(RolePermission(role_id=role_id, permission_id=permission_id, granted_at=datetime.now(UTC), granted_by=None))
        await _audit(session, "role.permission_assigned", role_id, "Role permission assigned")
    await session.commit()


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204, dependencies=[Depends(require_permission(ROLE_ASSIGN_PERMISSIONS))])
async def remove_role_permission(
    role_id: str,
    permission_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    role = await session.get(Role, role_id)
    if role and role.code == "super_admin":
        await _audit(session, "role.protected_rejected", role_id, "Cannot remove explicit Super Admin permissions")
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin permissions are protected")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id, RolePermission.permission_id == permission_id))
    await _audit(session, "role.permission_removed", role_id, "Role permission removed")
    await session.commit()


@router.get("/roles/{role_id}/channels", dependencies=[Depends(require_permission(ROLE_VIEW))])
async def list_role_channels(role_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[dict[str, str | bool]]:
    result = await session.execute(
        select(RoleLoginChannel).where(RoleLoginChannel.role_id == role_id).order_by(RoleLoginChannel.login_channel)
    )
    return [{"login_channel": channel.login_channel, "is_allowed": channel.is_allowed} for channel in result.scalars().all()]


@router.put("/roles/{role_id}/channels", status_code=204, dependencies=[Depends(require_permission(ROLE_ASSIGN_CHANNELS))])
async def replace_role_channels(
    role_id: str,
    payload: RoleChannelListAssignment,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    role = await session.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    channels = {item.login_channel.value: item.is_allowed for item in payload.channels}
    if role.code == "super_admin" and channels.get(LoginChannel.ADMIN.value) is not True:
        await _audit(session, "role.protected_rejected", role_id, "Cannot remove ADMIN channel from super_admin")
        await session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super Admin ADMIN channel is protected")
    await session.execute(delete(RoleLoginChannel).where(RoleLoginChannel.role_id == role_id))
    now = datetime.now(UTC)
    for login_channel, is_allowed in channels.items():
        session.add(RoleLoginChannel(role_id=role_id, login_channel=login_channel, is_allowed=is_allowed, created_at=now, created_by=None))
    await _audit(session, "role.channels_replaced", role_id, "Role login channels replaced")
    await session.commit()


@router.get("/roles/{role_id}/users", response_model=list[UserSummary], dependencies=[Depends(require_permission(ROLE_VIEW))])
async def list_role_users(role_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[UserSummary]:
    result = await session.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == role_id)
        .order_by(User.created_at.desc(), User.id)
    )
    return [UserSummary.model_validate(user, from_attributes=True) for user in result.scalars().all()]
