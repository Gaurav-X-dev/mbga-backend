"""Platform-wide reports for the Admin/Super Admin dashboard."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.merchants.models import Merchant
from app.modules.reports.constants import FINANCIAL_REPORTS, ExportFormat, ReportType
from app.modules.reports.export import export_response
from app.modules.reports.schemas import ReportResponse
from app.modules.reports.service import ReportScope, ReportService, report_range
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    get_effective_permission_service,
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.authorization.permission_checker import EffectivePermissionService
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/reports", tags=["Admin Reports"])

ADMIN_ONLY = Depends(require_login_channel(LoginChannel.ADMIN))
CAN_VIEW = Depends(require_permission("reports.view"))
CAN_EXPORT = Depends(require_permission("reports.export"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ContextDep = Annotated[AuthContext, Depends(require_authenticated_user)]
PermissionDep = Annotated[EffectivePermissionService, Depends(get_effective_permission_service)]


async def _authorize_detail(
    report_type: ReportType,
    context: AuthContext,
    permissions: EffectivePermissionService,
) -> None:
    if report_type in FINANCIAL_REPORTS:
        await permissions.require_permission(context, "expenses.view")
    if report_type is ReportType.PAYMENT_COLLECTION:
        await permissions.require_permission(context, "payments.reconcile")


async def _build(
    report_type: ReportType,
    date_from: datetime | None,
    date_to: datetime | None,
    customer_id: str | None,
    merchant_id: str | None,
    godown_id: str | None,
    session: AsyncSession,
    context: AuthContext,
    permissions: EffectivePermissionService,
) -> ReportResponse:
    if godown_id:
        raise ApiError(
            "FILTER_NOT_SUPPORTED",
            422,
            "godownId is not available because this deployment has no godown entity.",
        )
    if merchant_id and await session.get(Merchant, merchant_id) is None:
        raise ApiError("MERCHANT_NOT_FOUND", 404, "The selected merchant does not exist.")
    await _authorize_detail(report_type, context, permissions)
    start, end = report_range(date_from, date_to)
    return await ReportService(session, ReportScope.admin(merchant_id)).build(
        report_type,
        start,
        end,
        customer_id=customer_id,
    )


@router.get(
    "",
    response_model=ReportResponse,
    dependencies=[ADMIN_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 404, 422),
    summary="Platform report across all merchants or one selected merchant",
)
async def get_admin_report(
    session: SessionDep,
    context: ContextDep,
    permissions: PermissionDep,
    report_type: Annotated[ReportType, Query(alias="type")],
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
    godown_id: Annotated[str | None, Query(alias="godownId", max_length=36)] = None,
) -> ReportResponse:
    return await _build(
        report_type,
        date_from,
        date_to,
        customer_id,
        merchant_id,
        godown_id,
        session,
        context,
        permissions,
    )


@router.get(
    "/export",
    dependencies=[ADMIN_ONLY, CAN_VIEW, CAN_EXPORT],
    responses=error_responses(401, 403, 404, 422),
    summary="Export an all-merchant or selected-merchant platform report",
)
async def export_admin_report(
    session: SessionDep,
    context: ContextDep,
    permissions: PermissionDep,
    report_type: Annotated[ReportType, Query(alias="type")],
    export_format: Annotated[ExportFormat, Query(alias="format")],
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
    merchant_id: Annotated[str | None, Query(alias="merchantId", max_length=36)] = None,
    godown_id: Annotated[str | None, Query(alias="godownId", max_length=36)] = None,
):
    report = await _build(
        report_type,
        date_from,
        date_to,
        customer_id,
        merchant_id,
        godown_id,
        session,
        context,
        permissions,
    )
    return export_response(report, export_format)
