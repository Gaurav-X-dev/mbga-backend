from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.models import LoginSession
from app.modules.roles.permissions import (
    USER_ACTIVATE,
    USER_BLOCK,
    USER_CREATE,
    USER_ASSIGN_ROLES,
    USER_REMOVE_ROLES,
    USER_REVOKE_SESSIONS,
    USER_UPDATE,
    USER_UPDATE_ROLES,
    USER_VIEW,
    USER_VIEW_PERMISSIONS,
)
from app.modules.roles.models import Role, RoleLoginChannel
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.modules.users.role_repository import UserRoleRepository
from app.modules.users.role_schemas import (
    AllowedChannelsResponse,
    UserRoleAssignment,
    UserRoleResponse,
    UserRoleUpdate,
)
from app.modules.users.schemas import EffectivePermissionsResponse, UserCreate, UserListResponse, UserSummary, UserUpdate
from app.shared.authorization.dependencies import require_permission
from app.shared.database.session import get_db_session

router = APIRouter()


def _summary(user: User) -> UserSummary:
    return UserSummary.model_validate(user, from_attributes=True)


def _role_response(assignment: UserRole, role_code: str | None = None) -> UserRoleResponse:
    return UserRoleResponse(
        id=assignment.id,
        user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_code=role_code,
        assigned_at=assignment.assigned_at,
        assigned_by=assignment.assigned_by,
        is_active=assignment.is_active,
        valid_from=assignment.valid_from,
        valid_until=assignment.valid_until,
        scope_type=assignment.scope_type,
        scope_id=assignment.scope_id,
    )


async def _audit(session: AsyncSession, event_type: str, actor_user_id: str | None, entity_id: str, message: str) -> None:
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type=event_type,
            actor_user_id=actor_user_id,
            entity_type="user",
            entity_id=entity_id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )


@router.get("/users", response_model=UserListResponse, dependencies=[Depends(require_permission(USER_VIEW))])
async def list_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserListResponse:
    filters = []
    if search:
        like = f"%{search.lower()}%"
        filters.append(or_(func.lower(User.email).like(like), func.lower(User.username).like(like), User.mobile_number.like(like)))
    if status_filter:
        filters.append(User.status == status_filter.upper())
    stmt = select(User).where(*filters).order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)
    count_stmt = select(func.count()).select_from(User).where(*filters)
    users = (await session.execute(stmt)).scalars().all()
    total = int(await session.scalar(count_stmt) or 0)
    return UserListResponse(items=[_summary(user) for user in users], total=total, limit=limit, offset=offset)


@router.post("/users", response_model=UserSummary, dependencies=[Depends(require_permission(USER_CREATE))])
async def create_user(payload: UserCreate, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    if not payload.email and not payload.username and not payload.mobile_number:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="email, username or mobile number required")
    if payload.email or payload.username:
        result = await session.execute(
            select(User).where(
                or_(
                    User.email == (payload.email.lower() if payload.email else None),
                    User.username == (payload.username.lower() if payload.username else None),
                )
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists")
    now = datetime.now(UTC)
    user = User(
        id=str(uuid4()),
        email=payload.email.lower() if payload.email else None,
        username=payload.username.lower() if payload.username else None,
        full_name=payload.full_name,
        mobile_number=payload.mobile_number,
        country_code=payload.country_code if payload.mobile_number else None,
        password_hash=None,
        role=payload.role,
        status=payload.status.upper(),
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await _audit(session, "user.created", None, user.id, "User created")
    await session.commit()
    return _summary(user)


@router.get("/users/{user_id}", response_model=UserSummary, dependencies=[Depends(require_permission(USER_VIEW))])
async def get_user(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _summary(user)


@router.patch("/users/{user_id}", response_model=UserSummary, dependencies=[Depends(require_permission(USER_UPDATE))])
async def update_user(user_id: str, payload: UserUpdate, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key in {"email", "username"} and isinstance(value, str):
            value = value.lower()
        if key == "status" and isinstance(value, str):
            value = value.upper()
        setattr(user, key, value)
    user.updated_at = datetime.now(UTC)
    await _audit(session, "user.updated", None, user.id, "User updated")
    await session.commit()
    return _summary(user)


@router.post("/users/{user_id}/activate", response_model=UserSummary, dependencies=[Depends(require_permission(USER_ACTIVATE))])
async def activate_user(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.status = "ACTIVE"
    user.updated_at = datetime.now(UTC)
    await _audit(session, "user.activated", None, user.id, "User activated")
    await session.commit()
    return _summary(user)


@router.post("/users/{user_id}/block", response_model=UserSummary, dependencies=[Depends(require_permission(USER_BLOCK))])
async def block_user(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.status = "BLOCKED"
    user.updated_at = datetime.now(UTC)
    await _audit(session, "user.blocked", None, user.id, "User blocked")
    await session.commit()
    return _summary(user)


@router.post("/users/{user_id}/unblock", response_model=UserSummary, dependencies=[Depends(require_permission(USER_BLOCK))])
async def unblock_user(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> UserSummary:
    return await activate_user(user_id, session)


@router.get(
    "/users/{user_id}/effective-permissions",
    response_model=EffectivePermissionsResponse,
    dependencies=[Depends(require_permission(USER_VIEW_PERMISSIONS))],
)
async def get_effective_permissions(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    login_channel: LoginChannel = LoginChannel.ADMIN,
) -> EffectivePermissionsResponse:
    permissions = await UserRoleRepository(session).get_effective_permissions(
        user_id=user_id,
        login_channel=login_channel,
        now=datetime.now(UTC),
    )
    return EffectivePermissionsResponse(user_id=user_id, permissions=sorted(permissions))


@router.post("/users/{user_id}/logout-all", status_code=204, dependencies=[Depends(require_permission(USER_REVOKE_SESSIONS))])
async def logout_user_sessions(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> None:
    await session.execute(
        update(LoginSession)
        .where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await _audit(session, "user.sessions_revoked", None, user_id, "User sessions revoked")
    await session.commit()


@router.get("/users/{user_id}/roles", response_model=list[UserRoleResponse], dependencies=[Depends(require_permission(USER_VIEW))])
async def list_user_roles(user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[UserRoleResponse]:
    result = await session.execute(
        select(UserRole, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(UserRole.assigned_at.desc(), UserRole.id)
    )
    return [_role_response(assignment, role_code) for assignment, role_code in result.all()]


@router.post(
    "/users/{user_id}/roles",
    response_model=UserRoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(USER_ASSIGN_ROLES))],
)
async def assign_user_role(
    user_id: str,
    payload: UserRoleAssignment,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRoleResponse:
    user = await session.get(User, user_id)
    role = await session.get(Role, payload.role_id)
    if user is None or role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User or role not found")
    if not role.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive role cannot be assigned")
    existing = await session.execute(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == payload.role_id,
            UserRole.scope_type == payload.scope_type,
            UserRole.scope_id == payload.scope_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role assignment already exists")
    now = datetime.now(UTC)
    assignment = UserRole(
        id=str(uuid4()),
        user_id=user_id,
        role_id=payload.role_id,
        assigned_at=now,
        assigned_by=None,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        is_active=True,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
    )
    session.add(assignment)
    await _audit(session, "user_role.assigned", None, assignment.id, "User role assigned")
    await session.commit()
    return _role_response(assignment, role.code)


@router.patch(
    "/users/{user_id}/roles/{assignment_id}",
    response_model=UserRoleResponse,
    dependencies=[Depends(require_permission(USER_UPDATE_ROLES))],
)
async def update_user_role_assignment(
    user_id: str,
    assignment_id: str,
    payload: UserRoleUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserRoleResponse:
    assignment = await session.get(UserRole, assignment_id)
    if assignment is None or assignment.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(assignment, key, value)
    role = await session.get(Role, assignment.role_id)
    await _audit(session, "user_role.updated", None, assignment.id, "User role assignment updated")
    await session.commit()
    return _role_response(assignment, role.code if role else None)


@router.delete(
    "/users/{user_id}/roles/{assignment_id}",
    status_code=204,
    dependencies=[Depends(require_permission(USER_REMOVE_ROLES))],
)
async def remove_user_role_assignment(
    user_id: str,
    assignment_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    assignment = await session.get(UserRole, assignment_id)
    if assignment is None or assignment.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role assignment not found")
    assignment.is_active = False
    assignment.valid_until = assignment.valid_until or datetime.now(UTC)
    await _audit(session, "user_role.removed", None, assignment.id, "User role assignment removed")
    await session.commit()


@router.get(
    "/users/{user_id}/allowed-channels",
    response_model=AllowedChannelsResponse,
    dependencies=[Depends(require_permission(USER_VIEW_PERMISSIONS))],
)
async def get_allowed_channels(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AllowedChannelsResponse:
    now = datetime.now(UTC)
    result = await session.execute(
        select(RoleLoginChannel.login_channel)
        .join(Role, Role.id == RoleLoginChannel.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .join(User, User.id == UserRole.user_id)
        .where(User.id == user_id)
        .where(User.status == "ACTIVE")
        .where(UserRole.is_active.is_(True))
        .where((UserRole.valid_from.is_(None)) | (UserRole.valid_from <= now))
        .where((UserRole.valid_until.is_(None)) | (UserRole.valid_until > now))
        .where(Role.is_active.is_(True))
        .where(RoleLoginChannel.is_allowed.is_(True))
        .order_by(RoleLoginChannel.login_channel)
    )
    return AllowedChannelsResponse(user_id=user_id, channels=sorted(set(result.scalars().all())))
