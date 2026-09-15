from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.permissions.models import Permission
from app.modules.permissions.repository import PermissionRepository
from app.modules.permissions.schemas import (
    PermissionGroupedResponse,
    PermissionGroupResponse,
    PermissionListResponse,
    PermissionResponse,
)
from app.modules.permissions.service import PermissionService
from app.modules.roles.permissions import PERMISSION_VIEW
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session

router = APIRouter()


def get_permission_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> PermissionService:
    return PermissionService(PermissionRepository(session))


@router.get("/permissions", response_model=PermissionListResponse, dependencies=[Depends(require_permission(PERMISSION_VIEW))])
async def list_permissions(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    service: Annotated[PermissionService, Depends(get_permission_service)],
    search: str | None = None,
    module: str | None = None,
    action: str | None = None,
    is_active: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PermissionListResponse:
    filters = []
    if search:
        like = f"%{search.lower()}%"
        filters.append(func.lower(Permission.code).like(like) | func.lower(Permission.name).like(like))
    if module:
        filters.append(Permission.module == module)
    if action:
        filters.append(Permission.action == action)
    if is_active is not None:
        filters.append(Permission.is_active.is_(is_active))
    offset = (page - 1) * page_size
    stmt = select(Permission).where(*filters).order_by(Permission.module, Permission.action, Permission.code).limit(page_size).offset(offset)
    permissions = list((await session.execute(stmt)).scalars().all())
    total = int(await session.scalar(select(func.count()).select_from(Permission).where(*filters)) or 0)
    return PermissionListResponse(
        items=[PermissionResponse.model_validate(p, from_attributes=True) for p in permissions],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/permissions/grouped",
    response_model=PermissionGroupedResponse,
    dependencies=[Depends(require_permission(PERMISSION_VIEW))],
)
async def list_permissions_grouped(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    is_active: bool | None = True,
) -> PermissionGroupedResponse:
    filters = []
    if is_active is not None:
        filters.append(Permission.is_active.is_(is_active))
    permissions = list(
        (
            await session.execute(
                select(Permission).where(*filters).order_by(Permission.module, Permission.action, Permission.code)
            )
        )
        .scalars()
        .all()
    )
    groups: dict[str, list[PermissionResponse]] = {}
    for permission in permissions:
        groups.setdefault(permission.module, []).append(PermissionResponse.model_validate(permission, from_attributes=True))
    return PermissionGroupedResponse(
        groups=[PermissionGroupResponse(module=module, permissions=items) for module, items in groups.items()],
        total=len(permissions),
    )


@router.get(
    "/permissions/{permission_id}",
    response_model=PermissionResponse,
    dependencies=[Depends(require_permission(PERMISSION_VIEW))],
)
async def get_permission(
    permission_id: str,
    service: Annotated[PermissionService, Depends(get_permission_service)],
) -> PermissionResponse:
    permission = await service.get_permission(permission_id)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return PermissionResponse.model_validate(permission, from_attributes=True)
