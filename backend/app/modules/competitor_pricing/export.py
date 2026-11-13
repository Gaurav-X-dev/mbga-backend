"""Scoped merchant downloads; audit access is checked before querying protected rows."""

from fastapi.responses import Response

from app.modules.reports.export import _csv, xlsx_workbook
from app.shared.exceptions.api_error import ApiError

from .service import history_bounds

COMPARISON_COLUMNS = [
    "name",
    "code",
    "price",
    "difference",
    "differencePercentage",
    "updatedBy",
    "updatedByRole",
    "updatedAt",
    "effectiveDate",
    "notes",
]
AUDIT_COLUMNS = [
    "timestamp",
    "effectiveDate",
    "competitorName",
    "cylinderType",
    "locationPincode",
    "customerType",
    "oldPrice",
    "newPrice",
    "difference",
    "changedBy",
    "changedByRole",
    "notes",
]


async def pricing_export(
    service, filters, timeframe, start_date, end_date, format_, dataset, include_audit
):
    start, end = history_bounds(timeframe, start_date, end_date)
    need_audit = (format_ == "XLSX" and include_audit) or (format_ == "CSV" and dataset == "audit")
    if need_audit:
        await service.require_office()
    tables = {}
    if format_ == "XLSX" or dataset in {"snapshot", "comparison"}:
        comparison = await service.comparison(filters)
        snapshot = service.snapshot_view(filters, comparison)
        snapshot.update(
            pincode=filters.pincode,
            customerType=filters.customer_type,
            exportedPeriodStart=start,
            exportedPeriodEnd=end,
        )
        tables["snapshot"] = ("Market Snapshot", list(snapshot), [snapshot])
        tables["comparison"] = ("Price Comparison", COMPARISON_COLUMNS, comparison)
    if format_ == "XLSX" or dataset == "history":
        history = await service.history(filters, timeframe, start_date, end_date)
        keys = ["date", *sorted({k for row in history for k in row if k != "date"})]
        tables["history"] = ("Price History", keys, history)
    if need_audit:
        logs = await service.audit(
            cylinder=filters.cylinder_type,
            limit=10001,
            pincode=filters.pincode,
            customer_type=filters.customer_type,
            start_date=start,
            end_date=end,
        )
        if len(logs) > 10000:
            raise ApiError(
                "COMPETITOR_EXPORT_LIMIT",
                422,
                "More than 10,000 audit events match. Select a shorter date range.",
            )
        tables["audit"] = ("Audit Feed", AUDIT_COLUMNS, logs)
    if format_ == "CSV":
        _, columns, rows = tables[dataset]
        payload = _csv(columns, columns, rows)
        media, extension = "text/csv; charset=utf-8", "csv"
    else:
        payload = xlsx_workbook(
            [(name, columns, columns, rows) for name, columns, rows in tables.values()]
        )
        media, extension = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    filename = f"competitor_pricing_{filters.pincode}_{start}_{end}.{extension}"
    return Response(
        content=payload,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
