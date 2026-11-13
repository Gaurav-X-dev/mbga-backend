"""Admin receivables reports and customer reporting group maintenance."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.models import AuditLog
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.models import (
    CustomerProfile,
    CustomerReportGroup,
    CustomerReportMembership,
)
from app.modules.merchants.models import Merchant
from app.modules.reports.constants import ExportFormat
from app.modules.reports.export import export_response
from app.modules.reports.receivables import ReceivableFilters, ReceivablesService
from app.modules.reports.schemas import ReportResponse
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError

router = APIRouter(
    prefix="/receivables",
    tags=["Admin Reports"],
    dependencies=[
        Depends(require_login_channel(LoginChannel.ADMIN)),
        Depends(require_permission("reports.view")),
        Depends(require_permission("payments.reconcile")),
    ],
)
Session = Annotated[AsyncSession, Depends(get_db_session)]
Context = Annotated[AuthContext, Depends(require_authenticated_user)]
Filters = Annotated[ReceivableFilters, Query()]


@router.get("", response_model=ReportResponse)
async def report(session: Session, filters: Filters):
    return await ReceivablesService(session).build(filters)


class ExportFilters(ReceivableFilters):
    format: ExportFormat = ExportFormat.XLSX


@router.get("/export", dependencies=[Depends(require_permission("reports.export"))])
async def export(session: Session, filters: Annotated[ExportFilters, Query()]):
    return export_response(
        await ReceivablesService(session).build(filters, export=True), filters.format
    )


@router.get("/detail")
async def detail(session: Session, filters: Filters):
    return await ReceivablesService(session).detail(filters)


class GroupInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    active: bool = True


class AssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customerIds: list[str] = Field(min_length=1, max_length=100)
    groupId: str | None = Field(default=None, max_length=36)


def group_json(group):
    return {
        "id": group.id,
        "merchantId": group.merchant_id,
        "name": group.name,
        "active": group.active,
    }


async def merchant_exists(session, merchant_id):
    if await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404, "The selected merchant does not exist.")


def audit(session, context, entity_id, message):
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="CUSTOMER_REPORT_GROUP_UPDATED",
            actor_user_id=context.user_id,
            entity_type="customer_report_group",
            entity_id=entity_id,
            message=message,
            created_at=datetime.now(UTC),
        )
    )


@router.get("/groups")
async def groups(
    session: Session,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
):
    if merchant_id:
        await merchant_exists(session, merchant_id)
    query = select(CustomerReportGroup)
    if merchant_id:
        query = query.where(CustomerReportGroup.merchant_id == merchant_id)
    return [
        group_json(g)
        for g in (
            await session.scalars(query.order_by(CustomerReportGroup.name, CustomerReportGroup.id))
        ).all()
    ]


@router.post(
    "/groups", status_code=201, dependencies=[Depends(require_permission("customers.update"))]
)
async def create_group(
    payload: GroupInput,
    session: Session,
    context: Context,
    merchant_id: Annotated[str, Query(alias="merchantId", max_length=36)],
):
    await merchant_exists(session, merchant_id)
    group = CustomerReportGroup(
        id=str(uuid4()),
        merchant_id=merchant_id,
        name=payload.name,
        active=payload.active,
        updated_by=context.user_id,
        updated_at=datetime.now(UTC),
    )
    session.add(group)
    audit(session, context, group.id, f"Created group {group.name} for merchant {merchant_id}")
    await save_group(session)
    return group_json(group)


@router.patch("/groups/{group_id}", dependencies=[Depends(require_permission("customers.update"))])
async def update_group(
    group_id: str,
    payload: GroupInput,
    session: Session,
    context: Context,
    merchant_id: Annotated[str, Query(alias="merchantId", max_length=36)],
):
    group = await session.scalar(
        select(CustomerReportGroup)
        .where(CustomerReportGroup.id == group_id, CustomerReportGroup.merchant_id == merchant_id)
        .with_for_update()
    )
    if group is None:
        raise ApiError("GROUP_NOT_FOUND", 404, "The group does not belong to this merchant.")
    previous = group.name
    group.name, group.active = payload.name, payload.active
    group.updated_by, group.updated_at = context.user_id, datetime.now(UTC)
    audit(
        session,
        context,
        group.id,
        f"Group {previous} renamed to {group.name}; active={group.active}",
    )
    await save_group(session)
    return group_json(group)


async def save_group(session):
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(
            "GROUP_CONFLICT", 409, "A group with this name already exists for this merchant."
        ) from exc


@router.put("/groups/assignments", dependencies=[Depends(require_permission("customers.update"))])
async def assign(
    payload: AssignmentInput,
    session: Session,
    context: Context,
    merchant_id: Annotated[str, Query(alias="merchantId", max_length=36)],
):
    await merchant_exists(session, merchant_id)
    # Consistent lock ordering serializes concurrent assignments of the same customers.
    ids = sorted(set(payload.customerIds))
    customers = (
        await session.scalars(
            select(CustomerProfile)
            .where(CustomerProfile.id.in_(ids), CustomerProfile.merchant_id == merchant_id)
            .order_by(CustomerProfile.id)
            .with_for_update()
        )
    ).all()
    if len(customers) != len(ids):
        raise ApiError(
            "CUSTOMER_NOT_FOUND", 404, "Every selected customer must belong to this merchant."
        )
    if payload.groupId:
        group = await session.scalar(
            select(CustomerReportGroup)
            .where(
                CustomerReportGroup.id == payload.groupId,
                CustomerReportGroup.merchant_id == merchant_id,
            )
            .with_for_update()
        )
        if group is None or not group.active:
            raise ApiError(
                "GROUP_NOT_FOUND", 404, "Select an active group belonging to this merchant."
            )
    memberships = {
        m.customer_id: m
        for m in (
            await session.scalars(
                select(CustomerReportMembership).where(
                    CustomerReportMembership.customer_id.in_(ids)
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    for customer_id in ids:
        existing = memberships.get(customer_id)
        previous = existing.group_id if existing else "ungrouped"
        if payload.groupId is None:
            if existing:
                await session.delete(existing)
        elif existing:
            existing.group_id, existing.updated_by, existing.updated_at = (
                payload.groupId,
                context.user_id,
                now,
            )
        else:
            session.add(
                CustomerReportMembership(
                    customer_id=customer_id,
                    group_id=payload.groupId,
                    updated_by=context.user_id,
                    updated_at=now,
                )
            )
        audit(
            session,
            context,
            customer_id,
            f"Customer group: {previous} -> {payload.groupId or 'ungrouped'}; merchant {merchant_id}",
        )
    await session.commit()
    return {"updated": len(ids)}
