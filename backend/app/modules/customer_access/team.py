"""Simple employee presets and direct owner authorization, separate from branches."""

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from app.modules.customers.models import CustomerProfile
from app.modules.customers.validators import FieldErrors, validate_mobile
from app.modules.merchants.models import Merchant
from app.modules.users.identity import get_or_create_mobile_user
from app.shared.exceptions.api_error import ApiError
from app.shared.validation.names import check_name

from .branches import require_owner
from .models import CustomerBrand, CustomerOutlet, CustomerTeamMember
from .service import PERMISSIONS, audit

PRESETS = {
    "MANAGER": {
        "label": "Manager",
        "permissions": [
            "profile.view",
            "orders.view",
            "orders.create",
            "orders.cancel",
            "accounts.view",
            "inventory.view",
            "notifications.view",
        ],
    },
    "ACCOUNTS": {
        "label": "Accounts",
        "permissions": ["profile.view", "accounts.view", "accounts.pay", "notifications.view"],
    },
    "VIEW_ONLY": {
        "label": "View only",
        "permissions": [
            "profile.view",
            "orders.view",
            "accounts.view",
            "inventory.view",
            "notifications.view",
        ],
    },
}


class TeamInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=160)
    mobile: str = Field(min_length=10, max_length=20)
    scopeType: Literal["ALL", "ACCOUNT"] = "ACCOUNT"
    accountId: str | None = Field(default=None, max_length=36)
    preset: Literal["MANAGER", "ACCOUNTS", "VIEW_ONLY", "CUSTOM"] = "VIEW_ONLY"
    permissions: list[str] | None = Field(default=None, min_length=1, max_length=len(PERMISSIONS))

    @field_validator("name")
    @classmethod
    def real_name(cls, value):
        return check_name(value, field="name", required=True)

    @field_validator("permissions")
    @classmethod
    def valid_permissions(cls, value):
        if value is not None and not set(value) <= set(PERMISSIONS):
            raise ValueError("Choose permissions from the account permission catalogue.")
        return sorted(set(value)) if value is not None else None


def member_view(row):
    return {
        "id": row.id,
        "name": row.name,
        "mobile": row.mobile_number,
        "scopeType": row.scope_type,
        "accountId": row.scope_id if row.scope_type == "ACCOUNT" else None,
        "preset": row.preset,
        "permissions": json.loads(row.permissions),
        "status": row.status,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


async def owner_accounts(session, owner):
    children = list(
        await session.scalars(
            select(CustomerProfile)
            .join(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
            .join(CustomerBrand, CustomerBrand.id == CustomerOutlet.brand_id)
            .where(
                CustomerBrand.owner_customer_id == owner.id,
                CustomerProfile.merchant_id == owner.merchant_id,
            )
        )
    )
    return [owner, *children]


async def list_team(session, actor, owner_id, limit=20, offset=0):
    from sqlalchemy import func

    owner = await require_owner(session, actor, owner_id)
    filters = (
        CustomerTeamMember.owner_customer_id == owner.id,
        CustomerTeamMember.merchant_id == owner.merchant_id,
        CustomerTeamMember.status == "ACTIVE",
    )
    rows = await session.scalars(
        select(CustomerTeamMember)
        .where(*filters)
        .order_by(CustomerTeamMember.name, CustomerTeamMember.id)
        .offset(offset)
        .limit(limit)
    )
    total = await session.scalar(
        select(func.count()).select_from(CustomerTeamMember).where(*filters)
    )
    accounts = await owner_accounts(session, owner)
    return {
        "items": [member_view(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "presets": [{"code": code, **value} for code, value in PRESETS.items()],
        "permissionCatalog": list(PERMISSIONS),
        "accounts": [
            {"id": row.id, "name": row.name, "code": row.code, "status": row.status}
            for row in accounts
        ],
    }


async def save_member(session, actor, owner_id, payload, member_id=None):
    owner = await require_owner(session, actor, owner_id)
    accounts = await owner_accounts(session, owner)
    account_ids = {row.id for row in accounts}
    scope_id = owner.id if payload.scopeType == "ALL" else payload.accountId
    if not scope_id or (payload.scopeType == "ACCOUNT" and scope_id not in account_ids):
        raise ApiError("CUSTOMER_NOT_FOUND", 404, "Choose an account belonging to this owner.")
    errors = FieldErrors()
    mobile = validate_mobile(payload.mobile, errors)
    errors.raise_if_any()
    permissions = payload.permissions
    if permissions is None:
        if payload.preset == "CUSTOM":
            raise ApiError("VALIDATION_ERROR", 422, "Select at least one account permission.")
        permissions = PRESETS[payload.preset]["permissions"]
    preset = (
        payload.preset
        if payload.preset in PRESETS
        and set(permissions) == set(PRESETS[payload.preset]["permissions"])
        else "CUSTOM"
    )
    row = None
    if member_id:
        row = await session.scalar(
            select(CustomerTeamMember)
            .where(
                CustomerTeamMember.id == member_id,
                CustomerTeamMember.owner_customer_id == owner.id,
                CustomerTeamMember.merchant_id == owner.merchant_id,
                CustomerTeamMember.status == "ACTIVE",
            )
            .with_for_update()
        )
        if row is None:
            raise ApiError("NOT_FOUND", 404)
    user, _ = await get_or_create_mobile_user(
        session,
        mobile=mobile,
        full_name=payload.name,
        legacy_role="customer",
        new_user_status="PENDING",
    )
    if user.status not in {"ACTIVE", "PENDING"}:
        raise ApiError("ACCOUNT_INACTIVE", 409, "This person cannot receive account access.")
    if user.id == owner.user_id:
        raise ApiError(
            "CUSTOMER_TEAM_CONFLICT", 409, "The primary owner already has full account access."
        )
    existing = await session.scalar(
        select(CustomerTeamMember)
        .where(
            CustomerTeamMember.owner_customer_id == owner.id,
            CustomerTeamMember.user_id == user.id,
            CustomerTeamMember.scope_type == payload.scopeType,
            CustomerTeamMember.scope_id == scope_id,
        )
        .with_for_update()
    )
    if existing and (row is None or existing.id != row.id):
        if existing.status == "ACTIVE" or row is not None:
            raise ApiError(
                "CUSTOMER_TEAM_CONFLICT",
                409,
                "This person already has access for this scope. Edit that entry.",
            )
        row = existing
    now = datetime.now(UTC)
    if row is None:
        row = CustomerTeamMember(
            id=str(uuid4()),
            merchant_id=owner.merchant_id,
            owner_customer_id=owner.id,
            user_id=user.id,
            created_by=actor.user_id,
            created_at=now,
        )
        session.add(row)
    row.user_id = user.id
    row.name = payload.name
    row.mobile_number = mobile
    row.scope_type = payload.scopeType
    row.scope_id = scope_id
    row.preset = preset
    row.permissions = json.dumps(sorted(set(permissions)))
    row.status = "ACTIVE"
    row.updated_by = actor.user_id
    row.updated_at = now
    audit(
        session,
        actor,
        row.id,
        f"Team access saved: owner {owner.id}; scope {row.scope_type} {scope_id}; preset {preset}",
    )
    await session.flush()
    return member_view(row)


async def revoke_member(session, actor, owner_id, member_id):
    owner = await require_owner(session, actor, owner_id)
    row = await session.scalar(
        select(CustomerTeamMember)
        .where(
            CustomerTeamMember.id == member_id,
            CustomerTeamMember.owner_customer_id == owner.id,
            CustomerTeamMember.merchant_id == owner.merchant_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ApiError("NOT_FOUND", 404)
    if row.status != "REVOKED":
        row.status = "REVOKED"
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor.user_id
        audit(session, actor, row.id, "Revoked customer team access")
    return {"success": True}


async def active_team_rows(session, user_id):
    return list(
        await session.scalars(
            select(CustomerTeamMember)
            .join(CustomerProfile, CustomerProfile.id == CustomerTeamMember.owner_customer_id)
            .join(Merchant, Merchant.id == CustomerTeamMember.merchant_id)
            .where(
                CustomerTeamMember.user_id == user_id,
                CustomerTeamMember.status == "ACTIVE",
                CustomerProfile.merchant_id == CustomerTeamMember.merchant_id,
                CustomerProfile.status == "APPROVED",
                Merchant.status == "ACTIVE",
            )
        )
    )


async def team_accounts(session, user_id):
    rows = await active_team_rows(session, user_id)
    if not rows:
        return []
    owner_ids = {row.owner_customer_id for row in rows if row.scope_type == "ALL"}
    account_ids = {row.scope_id for row in rows if row.scope_type == "ACCOUNT"}
    # Scope is rechecked against the current hierarchy by permissions_for_many.
    return list(
        await session.scalars(
            select(CustomerProfile)
            .outerjoin(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
            .outerjoin(CustomerBrand, CustomerBrand.id == CustomerOutlet.brand_id)
            .where(
                or_(
                    CustomerProfile.id.in_(owner_ids),
                    CustomerProfile.id.in_(account_ids),
                    CustomerBrand.owner_customer_id.in_(owner_ids),
                ),
                CustomerProfile.status == "APPROVED",
            )
        )
    )


async def has_team_access(session, user_id):
    from .service import permissions_for_many

    accounts = await team_accounts(session, user_id)
    if not accounts:
        return False
    return any((await permissions_for_many(session, user_id, accounts)).values())
