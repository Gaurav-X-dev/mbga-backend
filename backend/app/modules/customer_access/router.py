"""One-level owner/branch management. No additional users, invitations or access roles."""

import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.business_schemas import CustomerRegistrationRequest, CustomerResponse
from app.modules.customers.dependencies import ActorDep, RegistrationDep
from app.modules.customers.editing import CustomerEditRequest
from app.modules.customers.mapping import CustomerViewLoader
from app.modules.customers.models import CustomerProfile
from app.modules.merchants.models import Merchant
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.business.admin_scope import AdminMerchantActorDep
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

from .models import CustomerBrand, CustomerOutlet
from .service import PERMISSIONS, audit, permissions_for_many

Session = Annotated[AsyncSession, Depends(get_db_session)]


class BrandInput(BaseModel):
    name: str = Field(min_length=1, max_length=160, pattern=r".*\S.*")
    ownerCustomerId: str | None = Field(default=None, max_length=36)


class Link(BaseModel):
    customerId: str = Field(min_length=1, max_length=36)


class BranchEditRequest(CustomerEditRequest):
    mobile: str | None = Field(default=None, min_length=10, max_length=20)
    permissions: list[str] | None = None

    @field_validator("permissions")
    @classmethod
    def valid_permissions(cls, value):
        if value is None or not set(value) <= set(PERMISSIONS):
            raise ValueError("Choose permissions from the branch permission catalogue.")
        return sorted(set(value))

    @field_validator("mobile")
    @classmethod
    def nonempty_mobile(cls, value):
        if value is None:
            raise ValueError("Branch phone number cannot be cleared.")
        return value


async def commit(session):
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise ApiError(
            "CUSTOMER_ACCESS_CONFLICT",
            409,
            "Customer phone or branch link already exists. Refresh before retrying.",
        ) from error


async def lock(session, merchant_id):
    await session.get(Merchant, merchant_id, with_for_update=True)


async def target(session, merchant_id, kind, id_):
    model = CustomerBrand if kind == "BRAND" else CustomerProfile
    row = await session.scalar(
        select(model).where(model.id == id_, model.merchant_id == merchant_id)
    )
    if row is None:
        raise ApiError("CUSTOMER_NOT_FOUND", 404)
    return row


async def hierarchy_view(session, actor, customer_id):
    current = await target(session, actor.require_merchant_id(), "OUTLET", customer_id)
    if actor.login_channel == LoginChannel.CUSTOMER and current.user_id != actor.user_id:
        from .branches import require_owner

        brand = await session.scalar(
            select(CustomerBrand)
            .join(CustomerOutlet, CustomerOutlet.brand_id == CustomerBrand.id)
            .where(CustomerOutlet.customer_id == current.id)
        )
        if not brand or not brand.owner_customer_id:
            raise ApiError("PERMISSION_DENIED", 403)
        await require_owner(session, actor, brand.owner_customer_id)
    link = await session.get(CustomerOutlet, current.id)
    brand = (
        await session.get(CustomerBrand, link.brand_id)
        if link
        else await session.scalar(
            select(CustomerBrand).where(CustomerBrand.owner_customer_id == current.id)
        )
    )
    owner = (
        await session.get(CustomerProfile, brand.owner_customer_id)
        if brand and brand.owner_customer_id
        else None
    )
    is_child = link is not None
    children = (
        list(
            await session.scalars(
                select(CustomerProfile)
                .join(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
                .where(CustomerOutlet.brand_id == brand.id)
                .order_by(CustomerProfile.name)
            )
        )
        if brand and not is_child
        else []
    )
    ids = [row.id for row in children]
    branch_links = (
        list(
            await session.scalars(select(CustomerOutlet).where(CustomerOutlet.customer_id.in_(ids)))
        )
        if ids
        else []
    )
    by_id = {row.customer_id: row for row in branch_links}

    def view(row):
        return {
            "id": row.id,
            "name": row.name,
            "code": row.code,
            "mobile": row.mobile_number,
            "status": row.status,
            "permissions": json.loads(by_id[row.id].permissions)
            if row.id in by_id and by_id[row.id].permissions is not None
            else list(PERMISSIONS),
        }

    return {
        "brand": {"id": brand.id, "name": brand.name} if brand else None,
        "owner": view(owner) if owner else None,
        "branches": [view(row) for row in children],
        "isOwner": bool(brand and not is_child),
        "accountKind": "BRANCH" if is_child else "OWNER" if brand else "STANDALONE",
        "canCreateBranches": not is_child
        and (actor.login_channel != LoginChannel.CUSTOMER or current.status == "APPROVED"),
        "permissionCatalog": list(PERMISSIONS),
    }


def build_router(channel):
    customer = channel == LoginChannel.CUSTOMER
    guards = [Depends(require_login_channel(channel))]
    if channel == LoginChannel.ADMIN:
        guards.append(Depends(require_permission("merchants.view")))
    router = APIRouter(prefix="/customer-access", tags=["Owner and branches"], dependencies=guards)
    Actor = ActorDep if channel != LoginChannel.ADMIN else AdminMerchantActorDep
    read = [] if customer else [Depends(require_permission("customers.view"))]
    write = [] if customer else [Depends(require_permission("customers.update"))]

    @router.get("/customers/{customer_id}/hierarchy", dependencies=read)
    async def hierarchy(customer_id: str, session: Session, actor: Actor):
        return await hierarchy_view(session, actor, customer_id)

    @router.post(
        "/customers/{owner_id}/branches",
        response_model=CustomerResponse,
        status_code=201,
        dependencies=write
        + ([] if customer else [Depends(require_permission("customers.create"))]),
    )
    async def create_owner_branch(
        owner_id: str,
        payload: CustomerRegistrationRequest,
        session: Session,
        actor: Actor,
        registration: RegistrationDep,
    ):
        from .branches import create_branch

        profile = await create_branch(session, actor, owner_id, payload, registration)
        await commit(session)
        return await CustomerViewLoader(session).customer_view(profile)

    @router.patch(
        "/customers/{owner_id}/branches/{branch_id}",
        response_model=CustomerResponse,
        dependencies=write,
    )
    async def edit_owner_branch(
        owner_id: str,
        branch_id: str,
        payload: BranchEditRequest,
        session: Session,
        actor: Actor,
        registration: RegistrationDep,
    ):
        from .branches import update_branch

        result = await update_branch(
            session, actor, owner_id, branch_id, payload, registration=registration
        )
        await commit(session)
        return result

    @router.delete(
        "/customers/{owner_id}/branches/{branch_id}",
        status_code=204,
        dependencies=[] if customer else [Depends(require_permission("customers.delete"))],
    )
    async def delete_owner_branch(owner_id: str, branch_id: str, session: Session, actor: Actor):
        from .branches import delete_branch

        await delete_branch(session, actor, owner_id, branch_id)
        await commit(session)

    from .team import TeamInput

    @router.get("/customers/{owner_id}/team", dependencies=read)
    async def team_list(
        owner_id: str,
        session: Session,
        actor: Actor,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        from .team import list_team

        return await list_team(session, actor, owner_id, limit, offset)

    @router.post("/customers/{owner_id}/team", dependencies=write, status_code=201)
    async def team_add(owner_id: str, payload: TeamInput, session: Session, actor: Actor):
        from .team import save_member

        result = await save_member(session, actor, owner_id, payload)
        await commit(session)
        return result

    @router.patch("/customers/{owner_id}/team/{member_id}", dependencies=write)
    async def team_update(
        owner_id: str, member_id: str, payload: TeamInput, session: Session, actor: Actor
    ):
        from .team import save_member

        result = await save_member(session, actor, owner_id, payload, member_id)
        await commit(session)
        return result

    @router.delete("/customers/{owner_id}/team/{member_id}", dependencies=write)
    async def team_remove(owner_id: str, member_id: str, session: Session, actor: Actor):
        from .team import revoke_member

        result = await revoke_member(session, actor, owner_id, member_id)
        await commit(session)
        return result

    if not customer:

        @router.get("/brands", dependencies=read)
        async def brands(
            session: Session,
            actor: Actor,
            search: str = "",
            limit: Annotated[int, Query(ge=1, le=100)] = 20,
            offset: Annotated[int, Query(ge=0)] = 0,
        ):
            rows = await session.scalars(
                select(CustomerBrand)
                .where(
                    CustomerBrand.merchant_id == actor.require_merchant_id(),
                    CustomerBrand.name.ilike("%" + search + "%"),
                )
                .order_by(CustomerBrand.name, CustomerBrand.id)
                .offset(offset)
                .limit(limit)
            )
            return [{"id": r.id, "name": r.name} for r in rows]

        @router.post("/brands", dependencies=write, status_code=201)
        async def brand_create(payload: BrandInput, session: Session, actor: Actor):
            await lock(session, actor.require_merchant_id())
            if payload.ownerCustomerId:
                from .branches import require_owner

                await require_owner(session, actor, payload.ownerCustomerId)
            row = CustomerBrand(
                id=str(uuid4()),
                merchant_id=actor.require_merchant_id(),
                name=payload.name.strip(),
                owner_customer_id=payload.ownerCustomerId,
            )
            session.add(row)
            audit(session, actor, row.id, "Created owner group")
            await commit(session)
            return {"id": row.id, "name": row.name}

        @router.post("/brands/{brand_id}/outlets", dependencies=write)
        async def link(brand_id: str, payload: Link, session: Session, actor: Actor):
            await lock(session, actor.require_merchant_id())
            brand = await target(session, actor.require_merchant_id(), "BRAND", brand_id)
            if brand.owner_customer_id:
                from .branches import require_owner

                await require_owner(session, actor, brand.owner_customer_id)
            await target(session, actor.require_merchant_id(), "OUTLET", payload.customerId)
            if await session.scalar(
                select(CustomerBrand.id).where(
                    CustomerBrand.owner_customer_id == payload.customerId
                )
            ):
                raise ApiError(
                    "CUSTOMER_ACCESS_CONFLICT", 409, "Owner accounts cannot become branches."
                )
            existing = await session.get(CustomerOutlet, payload.customerId)
            if existing:
                if existing.brand_id == brand_id:
                    return {"success": True}
                raise ApiError(
                    "CUSTOMER_ACCESS_CONFLICT", 409, "Customer already belongs to an owner."
                )
            session.add(CustomerOutlet(customer_id=payload.customerId, brand_id=brand.id))
            audit(session, actor, payload.customerId, "Linked branch to owner")
            await commit(session)
            return {"success": True}

        @router.get("/brands/{brand_id}/outlets", dependencies=read)
        async def outlets(brand_id: str, session: Session, actor: Actor):
            await target(session, actor.require_merchant_id(), "BRAND", brand_id)
            rows = await session.scalars(
                select(CustomerProfile)
                .join(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
                .where(CustomerOutlet.brand_id == brand_id)
            )
            return [{"id": r.id, "name": r.name, "code": r.code} for r in rows]

        @router.delete("/brands/{brand_id}/outlets/{customer_id}", dependencies=write)
        async def unlink(brand_id: str, customer_id: str, session: Session, actor: Actor):
            await lock(session, actor.require_merchant_id())
            await target(session, actor.require_merchant_id(), "BRAND", brand_id)
            row = await session.get(CustomerOutlet, customer_id)
            if not row or row.brand_id != brand_id:
                raise ApiError("CUSTOMER_NOT_FOUND", 404)
            from sqlalchemy import update

            from .models import CustomerTeamMember

            brand = await session.get(CustomerBrand, brand_id)
            await session.execute(
                update(CustomerTeamMember)
                .where(
                    CustomerTeamMember.owner_customer_id == brand.owner_customer_id,
                    CustomerTeamMember.scope_type == "ACCOUNT",
                    CustomerTeamMember.scope_id == customer_id,
                    CustomerTeamMember.status == "ACTIVE",
                )
                .values(status="REVOKED", updated_by=actor.user_id, updated_at=datetime.now(UTC))
            )
            await session.delete(row)
            audit(session, actor, customer_id, "Unlinked branch; customer retained")
            await commit(session)
            return {"success": True}

        @router.delete("/brands/{brand_id}", dependencies=write, status_code=204)
        async def remove_empty_brand(brand_id: str, session: Session, actor: Actor):
            await lock(session, actor.require_merchant_id())
            row = await target(session, actor.require_merchant_id(), "BRAND", brand_id)
            if await session.scalar(
                select(CustomerOutlet.customer_id)
                .where(CustomerOutlet.brand_id == brand_id)
                .limit(1)
            ):
                raise ApiError("CUSTOMER_BRAND_NOT_EMPTY", 409, "Unlink all branches first.")
            await session.delete(row)
            audit(session, actor, brand_id, "Removed empty owner group")
            await commit(session)

    if customer:

        @router.get("/context")
        async def context(
            session: Session, auth: Annotated[AuthContext, Depends(require_authenticated_user)]
        ):
            own = list(
                await session.scalars(
                    select(CustomerProfile).where(CustomerProfile.user_id == auth.user_id)
                )
            )
            brands = list(
                await session.scalars(
                    select(CustomerBrand).where(
                        CustomerBrand.owner_customer_id.in_(
                            [r.id for r in own if r.status == "APPROVED"]
                        )
                    )
                )
            )
            children = list(
                await session.scalars(
                    select(CustomerProfile)
                    .join(CustomerOutlet, CustomerOutlet.customer_id == CustomerProfile.id)
                    .where(CustomerOutlet.brand_id.in_([b.id for b in brands]))
                )
            )
            from .team import team_accounts

            assigned = await team_accounts(session, auth.user_id)
            accounts = {row.id: row for row in own + children + assigned}
            grants = await permissions_for_many(session, auth.user_id, list(accounts.values()))
            views = await CustomerViewLoader(session).ownership_for(list(accounts))
            return {
                "brands": [
                    {
                        "id": b.id,
                        "name": b.name,
                        "merchantId": b.merchant_id,
                        "ownerCustomerId": b.owner_customer_id,
                    }
                    for b in brands
                ],
                "accounts": [
                    {
                        "customerId": row.id,
                        "name": row.name,
                        "code": row.code,
                        "merchantId": row.merchant_id,
                        "permissions": sorted(grants[row.id]),
                        **views[row.id],
                        "canManageTeam": row.user_id == auth.user_id
                        and views[row.id]["accountKind"] != "BRANCH"
                        and row.status == "APPROVED",
                        "canCreateBranches": row.user_id == auth.user_id
                        and views[row.id]["canCreateBranches"]
                        and row.status == "APPROVED",
                        "accessKind": "PRIMARY"
                        if row.user_id == auth.user_id
                        else "OWNER"
                        if row in children
                        else "TEAM",
                    }
                    for row in accounts.values()
                    if grants[row.id] or row.user_id == auth.user_id
                ],
            }

        @router.get("/summary")
        async def summary(
            session: Session, auth: Annotated[AuthContext, Depends(require_authenticated_user)]
        ):
            from sqlalchemy import case, func

            from app.modules.payments.models import Invoice

            data = await context(session, auth)
            ids = [r["customerId"] for r in data["accounts"] if "accounts.view" in r["permissions"]]
            rows = await session.execute(
                select(
                    Invoice.customer_id,
                    func.sum(Invoice.total_amount),
                    func.sum(Invoice.paid_amount),
                    func.sum(Invoice.balance),
                    func.sum(
                        case(
                            (
                                (Invoice.balance > 0) & (Invoice.due_at < datetime.now(UTC)),
                                Invoice.balance,
                            ),
                            else_=0,
                        )
                    ),
                )
                .where(Invoice.customer_id.in_(ids))
                .group_by(Invoice.customer_id)
            )
            items = [
                {
                    "customerId": id_,
                    "totalInvoiced": int(invoiced or 0),
                    "totalPaid": int(paid or 0),
                    "runningBalance": int(balance or 0),
                    "overdueAmount": int(overdue or 0),
                }
                for id_, invoiced, paid, balance, overdue in rows
            ]
            return {
                "items": items,
                "totals": {
                    key: sum(row[key] for row in items)
                    for key in ["totalInvoiced", "totalPaid", "runningBalance", "overdueAmount"]
                },
                "currency": "INR",
                "amountUnit": "paise",
                "accountCount": len(ids),
            }

    return router
