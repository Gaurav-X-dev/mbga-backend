from app.modules.logistics.report import TripReportFilters, trip_report_filters
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.reports.fuel import FuelFilters, fuel_filter_params, fuel_all_time_range
from app.modules.reports.constants import FINANCIAL_REPORTS, ExportFormat, ReportType
from app.modules.reports.export import export_response
from app.modules.reports.schemas import ReportResponse
from app.modules.reports.service import ReportScope, ReportService, report_range
from app.shared.authorization.context import AuthContext
from app.shared.authorization.dependencies import (
    EffectivePermissionService,
    get_effective_permission_service,
    require_authenticated_user,
    require_login_channel,
    require_permission,
)
from app.shared.database.session import get_db_session
from app.shared.exceptions.api_error import ApiError
from app.shared.exceptions.openapi import error_responses

router = APIRouter(prefix="/reports", tags=["Merchant Reports"])

MERCHANT_ONLY = Depends(require_login_channel(LoginChannel.MERCHANT))
CAN_VIEW = Depends(require_permission("reports.view"))
CAN_EXPORT = Depends(require_permission("reports.export"))
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
ContextDep = Annotated[AuthContext, Depends(require_authenticated_user)]
PermissionDep = Annotated[EffectivePermissionService, Depends(get_effective_permission_service)]


async def _authorize_detail(
    report_type: ReportType, context: AuthContext, permissions: EffectivePermissionService
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
    godown_id: str | None,
    session: AsyncSession,
    actor,
    context: AuthContext,
    permissions: EffectivePermissionService,
    fuel_filters: FuelFilters | None = None,
    all_time: bool = False,
    trip_filters: TripReportFilters | None = None,
) -> ReportResponse:
    if godown_id:
        raise ApiError(
            "FILTER_NOT_SUPPORTED",
            422,
            "godownId is not available because this deployment has one merchant-level stock ledger and no godown entity.",
        )
    await _authorize_detail(report_type, context, permissions)
    if report_type is ReportType.FUEL and all_time:
        if date_from is not None or date_to is not None:
            raise ApiError("INVALID_DATE_RANGE",422,"Choose all time or an explicit date range.")
        start, end = await fuel_all_time_range(session, actor.require_merchant_id())
    else:
        start, end = report_range(date_from, date_to)
    return await ReportService(session, ReportScope.merchant(actor), fuel_filters, trip_filters).build(
        report_type, start, end, customer_id=customer_id
    )


@router.get(
    "",
    response_model=ReportResponse,
    dependencies=[MERCHANT_ONLY, CAN_VIEW],
    responses=error_responses(401, 403, 422),
    summary="Consolidated merchant report with drill-down details",
)
async def get_report(
    actor: ActorDep,
    session: SessionDep,
    context: ContextDep,
    permissions: PermissionDep,
    fuel_filters: Annotated[FuelFilters, Depends(fuel_filter_params)],
    trip_filters: Annotated[TripReportFilters, Depends(trip_report_filters)],
    report_type: Annotated[ReportType, Query(alias="type")],
    all_time: Annotated[bool, Query(alias="allTime")] = False,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
    godown_id: Annotated[str | None, Query(alias="godownId", max_length=36)] = None,
) -> ReportResponse:
    return await _build(report_type, date_from, date_to, customer_id, godown_id, session, actor, context, permissions, fuel_filters=fuel_filters, all_time=all_time, trip_filters=trip_filters)


@router.get(
    "/export",
    dependencies=[MERCHANT_ONLY, CAN_VIEW, CAN_EXPORT],
    responses=error_responses(401, 403, 422),
    summary="Download a report as CSV, XLSX, XML/XAML or JSON",
)
async def export_report(
    actor: ActorDep,
    session: SessionDep,
    context: ContextDep,
    permissions: PermissionDep,
    fuel_filters: Annotated[FuelFilters, Depends(fuel_filter_params)],
    trip_filters: Annotated[TripReportFilters, Depends(trip_report_filters)],
    report_type: Annotated[ReportType, Query(alias="type")],
    export_format: Annotated[ExportFormat, Query(alias="format")],
    all_time: Annotated[bool, Query(alias="allTime")] = False,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    customer_id: Annotated[str | None, Query(alias="customerId", max_length=36)] = None,
    godown_id: Annotated[str | None, Query(alias="godownId", max_length=36)] = None,
):
    report = await _build(report_type, date_from, date_to, customer_id, godown_id, session, actor, context, permissions, fuel_filters=fuel_filters, all_time=all_time, trip_filters=trip_filters)
    return export_response(report, export_format)
