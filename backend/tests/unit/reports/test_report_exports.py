from datetime import UTC, datetime, time
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.modules.reports.constants import ExportFormat, ReportType
from app.modules.reports.export import export_response
from app.modules.reports.schemas import ReportColumn, ReportPeriod, ReportResponse
from app.modules.reports.service import report_range
from app.shared.date_time.business_calendar import IST_TIMEZONE, business_today
from app.shared.exceptions.api_error import ApiError


def sample_report() -> ReportResponse:
    return ReportResponse(
        type=ReportType.PAYMENT_COLLECTION,
        title="Payments",
        period=ReportPeriod(**{"from": datetime(2026, 10, 1, tzinfo=UTC), "to": datetime(2026, 10, 2, tzinfo=UTC)}),
        summary=[],
        columns=[ReportColumn(key="payment", label="Payment"), ReportColumn(key="customer", label="Customer")],
        rows=[{"id": "1", "payment": "PAY-1", "customer": "=2+2", "_details": {"secret": "not exported"}}],
        generatedAt=datetime.now(UTC),
    )


async def _body(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


@pytest.mark.asyncio
async def test_csv_export_blocks_formula_injection_and_omits_details():
    response = export_response(sample_report(), ExportFormat.CSV)
    payload = await _body(response)
    assert b"'=2+2" in payload
    assert b"secret" not in payload
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_excel_export_is_a_valid_xlsx_archive():
    response = export_response(sample_report(), ExportFormat.EXCEL)
    payload = await _body(response)
    with ZipFile(BytesIO(payload)) as archive:
        assert "xl/worksheets/sheet1.xml" in archive.namelist()
        assert b"PAY-1" in archive.read("xl/worksheets/sheet1.xml")


def test_report_range_rejects_reverse_and_unbounded_ranges():
    with pytest.raises(ApiError):
        report_range(datetime(2026, 10, 2, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(ApiError):
        report_range(datetime(2010, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC))


def test_default_report_range_is_the_complete_india_business_day():
    start, end = report_range(None, None)

    assert start.astimezone(IST_TIMEZONE).date() == business_today()
    assert start.astimezone(IST_TIMEZONE).time() == time.min
    assert end.astimezone(IST_TIMEZONE).date() == business_today()
    assert end.astimezone(IST_TIMEZONE).time() == time.max


def test_report_timestamps_are_serialized_with_india_offset():
    payload = sample_report().model_dump(mode="json", by_alias=True)

    assert payload["period"]["from"].endswith("+05:30")
    assert payload["generatedAt"].endswith("+05:30")
