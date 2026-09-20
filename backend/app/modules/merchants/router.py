from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.models import LoginSession
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.merchants.schemas import (
    MerchantCreate,
    MerchantListResponse,
    MerchantResponse,
    MerchantUpdate,
    MerchantUserCreate,
    MerchantUserResponse,
    MerchantUserUpdate,
)
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user, require_login_channel, require_permission
from app.shared.database.session import get_db_session

router = APIRouter(prefix="/merchants", tags=["Admin Merchants"])


def _merchant_response(merchant: Merchant, primary_user_id: str | None = None) -> MerchantResponse:
    return MerchantResponse(
        id=merchant.id,
        merchant_code=merchant.code,
        business_name=merchant.name,
        contact_person_name=merchant.contact_person_name,
        mobile_number=merchant.mobile_number,
        email=merchant.email,
        gst_number=merchant.gst_number,
        address_line_1=merchant.address_line_1,
        address_line_2=merchant.address_line_2,
        city=merchant.city,
        state=merchant.state,
        postal_code=merchant.postal_code,
        primary_user_id=primary_user_id,
        status=merchant.status,
        approval_status=merchant.approval_status,
        created_at=merchant.created_at,
    )


def _merchant_user_response(merchant_user: MerchantUser, user: User) -> MerchantUserResponse:
    return MerchantUserResponse(
        id=merchant_user.id,
        merchant_id=merchant_user.merchant_id,
        user_id=user.id,
        full_name=user.full_name,
        mobile_number=user.mobile_number,
        email=user.email,
        staff_type=merchant_user.staff_type,
        status=merchant_user.status,
        created_at=merchant_user.created_at,
    )


async def _audit(session: AsyncSession, event_type: str, actor_user_id: str | None, entity_type: str, entity_id: str, message: str) -> None:
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type=event_type,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )


def _normalize_mobile_or_422(mobile_number: str) -> str:
    try:
        return normalize_mobile_number(mobile_number)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_MOBILE_NUMBER", "message": str(exc)}) from exc


async def _get_role(session: AsyncSession, code: str) -> Role:
    role = await session.scalar(select(Role).where(Role.code == code, Role.is_active.is_(True)))
    if role is None:
        raise HTTPException(status_code=500, detail={"code": "ROLE_NOT_SEEDED", "message": f"{code} role is missing"})
    return role


async def _assign_role(session: AsyncSession, user_id: str, role: Role, scope_type: str, scope_id: str, actor_user_id: str | None) -> None:
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.scope_type == scope_type,
            UserRole.scope_id == scope_id,
        )
    )
    if existing:
        existing.is_active = True
        existing.valid_until = None
        return
    session.add(
        UserRole(
            id=str(uuid4()),
            user_id=user_id,
            role_id=role.id,
            assigned_at=datetime.now(UTC),
            assigned_by=actor_user_id,
            valid_from=None,
            valid_until=None,
            is_active=True,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    )


async def _get_or_create_user(session: AsyncSession, *, mobile: str, full_name: str, email: str | None, role: str) -> User:
    existing = await session.scalar(select(User).where(User.mobile_number == mobile))
    if existing:
        if existing.status == "BLOCKED":
            raise HTTPException(status_code=409, detail={"code": "MOBILE_ALREADY_BLOCKED", "message": "Mobile belongs to a blocked user"})
        return existing
    if email:
        email_existing = await session.scalar(select(User).where(User.email == email.lower()))
        if email_existing:
            raise HTTPException(status_code=409, detail={"code": "EMAIL_ALREADY_EXISTS", "message": "Email already exists"})
    now = datetime.now(UTC)
    user = User(
        id=str(uuid4()),
        email=email.lower() if email else None,
        username=None,
        full_name=full_name,
        mobile_number=mobile,
        country_code="+91",
        password_hash=None,
        role=role,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.flush()
    return user


@router.post(
    "",
    response_model=MerchantResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.create"))],
)
async def create_merchant(
    payload: MerchantCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> MerchantResponse:
    mobile = _normalize_mobile_or_422(payload.mobile_number)
    code = payload.merchant_code.upper()
    if await session.scalar(select(Merchant).where(Merchant.code == code)):
        raise HTTPException(status_code=409, detail={"code": "MERCHANT_CODE_EXISTS", "message": "Merchant code already exists"})
    if await session.scalar(select(Merchant).where(Merchant.mobile_number == mobile)):
        raise HTTPException(status_code=409, detail={"code": "MERCHANT_MOBILE_EXISTS", "message": "Merchant mobile already exists"})
    now = datetime.now(UTC)
    user = await _get_or_create_user(
        session,
        mobile=mobile,
        full_name=payload.contact_person_name,
        email=payload.email,
        role="manager",
    )
    merchant = Merchant(
        id=str(uuid4()),
        code=code,
        name=payload.business_name,
        mobile_number=mobile,
        contact_person_name=payload.contact_person_name,
        email=payload.email.lower() if payload.email else None,
        gst_number=payload.gst_number,
        address_line_1=payload.address_line_1,
        address_line_2=payload.address_line_2,
        city=payload.city,
        state=payload.state,
        postal_code=payload.postal_code,
        status="ACTIVE",
        approval_status="APPROVED",
        created_by=context.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(merchant)
    await session.flush()
    merchant_user = MerchantUser(
        id=str(uuid4()),
        merchant_id=merchant.id,
        user_id=user.id,
        staff_type="PRIMARY_MANAGER",
        status="ACTIVE",
        notes="Created by Admin merchant creation API",
        created_at=now,
        updated_at=now,
    )
    session.add(merchant_user)
    await _assign_role(session, user.id, await _get_role(session, "manager"), "merchant", merchant.id, context.user_id)
    await _audit(session, "merchant.created", context.user_id, "merchant", merchant.id, "Merchant created")
    await session.commit()
    return _merchant_response(merchant, user.id)


@router.get("", response_model=MerchantListResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.view"))])
async def list_merchants(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    search: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    merchant_code: str | None = None,
    city: str | None = None,
    state: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MerchantListResponse:
    filters = []
    if search:
        like = f"%{search.lower()}%"
        filters.append(or_(func.lower(Merchant.name).like(like), func.lower(Merchant.code).like(like), Merchant.mobile_number.like(like)))
    if status_filter:
        filters.append(Merchant.status == status_filter.upper())
    if merchant_code:
        filters.append(Merchant.code == merchant_code.upper())
    if city:
        filters.append(func.lower(Merchant.city) == city.lower())
    if state:
        filters.append(func.lower(Merchant.state) == state.lower())
    rows = (await session.execute(select(Merchant).where(*filters).order_by(Merchant.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    total = int(await session.scalar(select(func.count()).select_from(Merchant).where(*filters)) or 0)
    return MerchantListResponse(items=[_merchant_response(row) for row in rows], total=total, limit=limit, offset=offset)


async def _load_merchant(session: AsyncSession, merchant_id: str) -> Merchant:
    merchant = await session.get(Merchant, merchant_id)
    if merchant is None:
        raise HTTPException(status_code=404, detail={"code": "MERCHANT_NOT_FOUND", "message": "Merchant not found"})
    return merchant


@router.get("/{merchant_id}", response_model=MerchantResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.view"))])
async def get_merchant(merchant_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> MerchantResponse:
    merchant = await _load_merchant(session, merchant_id)
    primary = await session.scalar(select(MerchantUser).where(MerchantUser.merchant_id == merchant.id).order_by(MerchantUser.created_at))
    return _merchant_response(merchant, primary.user_id if primary else None)


@router.patch("/{merchant_id}", response_model=MerchantResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.update"))])
async def update_merchant(
    merchant_id: str,
    payload: MerchantUpdate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> MerchantResponse:
    merchant = await _load_merchant(session, merchant_id)
    updates = payload.model_dump(exclude_unset=True)
    if "business_name" in updates:
        merchant.name = updates.pop("business_name")
    for key, value in updates.items():
        if key == "email" and isinstance(value, str):
            value = value.lower()
        setattr(merchant, key, value)
    merchant.updated_at = datetime.now(UTC)
    await _audit(session, "merchant.updated", context.user_id, "merchant", merchant.id, "Merchant updated")
    await session.commit()
    return _merchant_response(merchant)


async def _set_merchant_status(session: AsyncSession, merchant: Merchant, status_value: str, actor_user_id: str | None) -> MerchantResponse:
    merchant.status = status_value
    merchant.updated_at = datetime.now(UTC)
    if status_value == "BLOCKED":
        result = await session.execute(select(MerchantUser.user_id).where(MerchantUser.merchant_id == merchant.id))
        user_ids = list(result.scalars().all())
        if user_ids:
            await session.execute(update(LoginSession).where(LoginSession.user_id.in_(user_ids), LoginSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    await _audit(session, f"merchant.{status_value.lower()}", actor_user_id, "merchant", merchant.id, f"Merchant {status_value.lower()}")
    await session.commit()
    return _merchant_response(merchant)


@router.post("/{merchant_id}/activate", response_model=MerchantResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.activate"))])
async def activate_merchant(merchant_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MerchantResponse:
    return await _set_merchant_status(session, await _load_merchant(session, merchant_id), "ACTIVE", context.user_id)


@router.post("/{merchant_id}/block", response_model=MerchantResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.block"))])
async def block_merchant(merchant_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MerchantResponse:
    return await _set_merchant_status(session, await _load_merchant(session, merchant_id), "BLOCKED", context.user_id)


@router.post("/{merchant_id}/unblock", response_model=MerchantResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchants.activate"))])
async def unblock_merchant(merchant_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MerchantResponse:
    return await _set_merchant_status(session, await _load_merchant(session, merchant_id), "ACTIVE", context.user_id)


@router.get("/{merchant_id}/users", response_model=list[MerchantUserResponse], dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchant_users.view"))])
async def list_merchant_users(merchant_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> list[MerchantUserResponse]:
    await _load_merchant(session, merchant_id)
    result = await session.execute(select(MerchantUser, User).join(User, User.id == MerchantUser.user_id).where(MerchantUser.merchant_id == merchant_id))
    return [_merchant_user_response(mu, user) for mu, user in result.all()]


@router.post("/{merchant_id}/users", response_model=MerchantUserResponse, status_code=201, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchant_users.create"))])
async def create_merchant_user(merchant_id: str, payload: MerchantUserCreate, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MerchantUserResponse:
    await _load_merchant(session, merchant_id)
    user = await _get_or_create_user(session, mobile=_normalize_mobile_or_422(payload.mobile_number), full_name=payload.full_name, email=payload.email, role="manager")
    now = datetime.now(UTC)
    existing = await session.scalar(select(MerchantUser).where(MerchantUser.merchant_id == merchant_id, MerchantUser.user_id == user.id))
    if existing:
        raise HTTPException(status_code=409, detail={"code": "MERCHANT_USER_EXISTS", "message": "Merchant user already exists"})
    merchant_user = MerchantUser(id=str(uuid4()), merchant_id=merchant_id, user_id=user.id, staff_type=payload.staff_type, status="ACTIVE", notes=None, created_at=now, updated_at=now)
    session.add(merchant_user)
    await _assign_role(session, user.id, await _get_role(session, "manager"), "merchant", merchant_id, context.user_id)
    await _audit(session, "merchant_user.created", context.user_id, "merchant_user", merchant_user.id, "Merchant user created")
    await session.commit()
    return _merchant_user_response(merchant_user, user)


@router.get("/{merchant_id}/users/{user_id}", response_model=MerchantUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchant_users.view"))])
async def get_merchant_user(merchant_id: str, user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)]) -> MerchantUserResponse:
    result = await session.execute(select(MerchantUser, User).join(User, User.id == MerchantUser.user_id).where(MerchantUser.merchant_id == merchant_id, MerchantUser.user_id == user_id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MERCHANT_USER_NOT_FOUND", "message": "Merchant user not found"})
    return _merchant_user_response(row[0], row[1])


@router.patch("/{merchant_id}/users/{user_id}", response_model=MerchantUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.ADMIN)), Depends(require_permission("merchant_users.update"))])
async def update_merchant_user(merchant_id: str, user_id: str, payload: MerchantUserUpdate, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> MerchantUserResponse:
    result = await session.execute(select(MerchantUser, User).join(User, User.id == MerchantUser.user_id).where(MerchantUser.merchant_id == merchant_id, MerchantUser.user_id == user_id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "MERCHANT_USER_NOT_FOUND", "message": "Merchant user not found"})
    merchant_user, user = row
    updates = payload.model_dump(exclude_unset=True)
    if "full_name" in updates:
        user.full_name = updates["full_name"]
    if "email" in updates:
        user.email = updates["email"].lower() if updates["email"] else None
    if "staff_type" in updates:
        merchant_user.staff_type = updates["staff_type"]
    if "status" in updates:
        merchant_user.status = updates["status"].upper()
    user.updated_at = merchant_user.updated_at = datetime.now(UTC)
    await _audit(session, "merchant_user.updated", context.user_id, "merchant_user", merchant_user.id, "Merchant user updated")
    await session.commit()
    return _merchant_user_response(merchant_user, user)
