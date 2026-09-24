from datetime import UTC, datetime, time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.models import LoginSession
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.delivery_users.schemas import DeliveryUserCreate, DeliveryUserListResponse, DeliveryUserResponse, DeliveryUserType, DeliveryUserUpdate
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import require_authenticated_user, require_login_channel, require_permission
from app.shared.database.session import get_db_session

router = APIRouter(prefix="/delivery-users", tags=["Merchant Delivery Users"])


def _expiry_datetime(value):
    return datetime.combine(value, time.min) if value else None


def _response(profile: DeliveryProfile, user: User) -> DeliveryUserResponse:
    role = "driver" if profile.delivery_user_type == "DRIVER" else "helper"
    return DeliveryUserResponse(
        id=profile.id,
        merchant_id=profile.merchant_id,
        user_id=user.id,
        delivery_user_type=profile.delivery_user_type,
        full_name=user.full_name,
        mobile_number=user.mobile_number,
        email=user.email,
        employee_code=profile.employee_code,
        driving_license_number=profile.driving_license_number,
        driving_license_expiry=profile.driving_license_expiry,
        address=profile.address,
        status=profile.status,
        approval_status=profile.approval_status,
        role=role,
        created_at=profile.created_at,
    )


async def _audit(session: AsyncSession, event_type: str, actor_user_id: str | None, entity_id: str, message: str) -> None:
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type=event_type,
            actor_user_id=actor_user_id,
            entity_type="delivery_profile",
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


async def _merchant_scope(session: AsyncSession, context: AuthContext) -> str:
    result = await session.execute(
        select(Merchant.id)
        .join(MerchantUser, MerchantUser.merchant_id == Merchant.id)
        .where(MerchantUser.user_id == context.user_id)
        .where(MerchantUser.status == "ACTIVE")
        .where(Merchant.status == "ACTIVE")
        .where(Merchant.approval_status == "APPROVED")
    )
    merchant_id = result.scalar_one_or_none()
    if merchant_id is None:
        raise HTTPException(status_code=403, detail={"code": "MERCHANT_SCOPE_REQUIRED", "message": "Merchant scope required"})
    return merchant_id


async def _role(session: AsyncSession, code: str) -> Role:
    role = await session.scalar(select(Role).where(Role.code == code, Role.is_active.is_(True)))
    if role is None:
        raise HTTPException(status_code=500, detail={"code": "ROLE_NOT_SEEDED", "message": f"{code} role is missing"})
    return role


async def _assign_role(session: AsyncSession, user_id: str, role: Role, actor_user_id: str | None, merchant_id: str) -> None:
    existing = await session.scalar(
        select(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id == role.id,
            UserRole.scope_type == "merchant",
            UserRole.scope_id == merchant_id,
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
            scope_type="merchant",
            scope_id=merchant_id,
        )
    )


async def _get_or_create_user(session: AsyncSession, *, mobile: str, full_name: str, email: str | None, role: str) -> User:
    existing = await session.scalar(select(User).where(User.mobile_number == mobile))
    if existing:
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
    response_model=DeliveryUserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.create"))],
)
async def create_delivery_user(
    payload: DeliveryUserCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
) -> DeliveryUserResponse:
    merchant_id = await _merchant_scope(session, context)
    if await session.scalar(select(DeliveryProfile).where(DeliveryProfile.merchant_id == merchant_id, DeliveryProfile.employee_code == payload.employee_code)):
        raise HTTPException(status_code=409, detail={"code": "EMPLOYEE_CODE_EXISTS", "message": "Employee code already exists for merchant"})
    mobile = _normalize_mobile_or_422(payload.mobile_number)
    if await session.scalar(select(DeliveryProfile).join(User, User.id == DeliveryProfile.user_id).where(User.mobile_number == mobile)):
        raise HTTPException(status_code=409, detail={"code": "DELIVERY_MOBILE_EXISTS", "message": "Delivery mobile already exists"})
    role_code = "driver" if payload.delivery_user_type == DeliveryUserType.DRIVER else "helper"
    user = await _get_or_create_user(session, mobile=mobile, full_name=payload.full_name, email=payload.email, role=role_code)
    now = datetime.now(UTC)
    profile = DeliveryProfile(
        id=str(uuid4()),
        merchant_id=merchant_id,
        user_id=user.id,
        delivery_user_type=payload.delivery_user_type.value,
        employee_code=payload.employee_code,
        driving_license_number=payload.driving_license_number,
        driving_license_expiry=_expiry_datetime(payload.driving_license_expiry),
        address=payload.address,
        status="ACTIVE",
        approval_status="APPROVED",
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    await _assign_role(session, user.id, await _role(session, role_code), context.user_id, merchant_id)
    await _audit(session, "delivery_user.created", context.user_id, profile.id, "Delivery user created")
    await session.commit()
    return _response(profile, user)


@router.get("", response_model=DeliveryUserListResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.view"))])
async def list_delivery_users(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    context: Annotated[AuthContext, Depends(require_authenticated_user)],
    search: str | None = None,
    delivery_user_type: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    employee_code: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DeliveryUserListResponse:
    merchant_id = await _merchant_scope(session, context)
    filters = [DeliveryProfile.merchant_id == merchant_id]
    if delivery_user_type:
        filters.append(DeliveryProfile.delivery_user_type == delivery_user_type.upper())
    if status_filter:
        filters.append(DeliveryProfile.status == status_filter.upper())
    if employee_code:
        filters.append(DeliveryProfile.employee_code == employee_code)
    if search:
        like = f"%{search.lower()}%"
        filters.append(or_(func.lower(User.full_name).like(like), User.mobile_number.like(like), func.lower(DeliveryProfile.employee_code).like(like)))
    stmt = select(DeliveryProfile, User).join(User, User.id == DeliveryProfile.user_id).where(*filters).order_by(DeliveryProfile.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).all()
    total = int(await session.scalar(select(func.count()).select_from(DeliveryProfile).join(User, User.id == DeliveryProfile.user_id).where(*filters)) or 0)
    return DeliveryUserListResponse(items=[_response(profile, user) for profile, user in rows], total=total, limit=limit, offset=offset)


async def _load_scoped_profile(session: AsyncSession, context: AuthContext, delivery_user_id: str) -> tuple[DeliveryProfile, User]:
    merchant_id = await _merchant_scope(session, context)
    result = await session.execute(
        select(DeliveryProfile, User)
        .join(User, User.id == DeliveryProfile.user_id)
        .where(DeliveryProfile.id == delivery_user_id, DeliveryProfile.merchant_id == merchant_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "DELIVERY_USER_NOT_FOUND", "message": "Delivery user not found"})
    return row[0], row[1]


@router.get("/{delivery_user_id}", response_model=DeliveryUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.view"))])
async def get_delivery_user(delivery_user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> DeliveryUserResponse:
    profile, user = await _load_scoped_profile(session, context, delivery_user_id)
    return _response(profile, user)


@router.patch("/{delivery_user_id}", response_model=DeliveryUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.update"))])
async def update_delivery_user(delivery_user_id: str, payload: DeliveryUserUpdate, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> DeliveryUserResponse:
    profile, user = await _load_scoped_profile(session, context, delivery_user_id)
    updates = payload.model_dump(exclude_unset=True)
    if "full_name" in updates:
        user.full_name = updates["full_name"]
    if "email" in updates:
        user.email = updates["email"].lower() if updates["email"] else None
    for key in ["employee_code", "driving_license_number", "address"]:
        if key in updates:
            setattr(profile, key, updates[key])
    if "driving_license_expiry" in updates:
        profile.driving_license_expiry = _expiry_datetime(updates["driving_license_expiry"])
    user.updated_at = profile.updated_at = datetime.now(UTC)
    await _audit(session, "delivery_user.updated", context.user_id, profile.id, "Delivery user updated")
    await session.commit()
    return _response(profile, user)


async def _set_status(session: AsyncSession, context: AuthContext, delivery_user_id: str, status_value: str) -> DeliveryUserResponse:
    profile, user = await _load_scoped_profile(session, context, delivery_user_id)
    profile.status = status_value
    profile.updated_at = datetime.now(UTC)
    if status_value == "BLOCKED":
        user.status = "BLOCKED"
        await session.execute(update(LoginSession).where(LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    elif status_value == "ACTIVE":
        user.status = "ACTIVE"
    user.updated_at = datetime.now(UTC)
    await _audit(session, f"delivery_user.{status_value.lower()}", context.user_id, profile.id, f"Delivery user {status_value.lower()}")
    await session.commit()
    return _response(profile, user)


@router.post("/{delivery_user_id}/activate", response_model=DeliveryUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.activate"))])
async def activate_delivery_user(delivery_user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> DeliveryUserResponse:
    return await _set_status(session, context, delivery_user_id, "ACTIVE")


@router.post("/{delivery_user_id}/block", response_model=DeliveryUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.block"))])
async def block_delivery_user(delivery_user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> DeliveryUserResponse:
    return await _set_status(session, context, delivery_user_id, "BLOCKED")


@router.post("/{delivery_user_id}/unblock", response_model=DeliveryUserResponse, dependencies=[Depends(require_login_channel(LoginChannel.MERCHANT)), Depends(require_permission("delivery_users.activate"))])
async def unblock_delivery_user(delivery_user_id: str, session: Annotated[AsyncSession, Depends(get_db_session)], context: Annotated[AuthContext, Depends(require_authenticated_user)]) -> DeliveryUserResponse:
    return await _set_status(session, context, delivery_user_id, "ACTIVE")
