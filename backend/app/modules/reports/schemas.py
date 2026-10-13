from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.modules.reports.constants import ReportType
from app.shared.date_time.business_calendar import IST_TIMEZONE

_CAMEL = ConfigDict(populate_by_name=True, serialize_by_alias=True)


def _as_ist(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return moment.astimezone(IST_TIMEZONE).isoformat(timespec="seconds")


ReportTime = Annotated[
    datetime,
    PlainSerializer(_as_ist, return_type=str, when_used="json-unless-none"),
]


class ReportPeriod(BaseModel):
    date_from: ReportTime = Field(alias="from")
    date_to: ReportTime = Field(alias="to")
    model_config = _CAMEL


class ReportSummaryItem(BaseModel):
    label: str
    value: str | int | float
    model_config = _CAMEL


class ReportColumn(BaseModel):
    key: str
    label: str
    align: Literal["left", "right", "center"] = "left"
    model_config = _CAMEL


class StatusBadge(BaseModel):
    label: str
    color: Literal["success", "warning", "danger", "info", "neutral"] = "neutral"
    model_config = _CAMEL


class DetailField(BaseModel):
    label: str
    value: Any = None
    highlight: bool = False
    model_config = _CAMEL


class DetailBreakdown(BaseModel):
    title: str
    quantity: int | float | None = None
    amount: int | float | None = None
    subtitle: str | None = None
    model_config = _CAMEL


class AuditTrailItem(BaseModel):
    action: str
    timestamp: ReportTime
    user: str | None = None
    model_config = _CAMEL


class ReportRowDetail(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    status_badge: StatusBadge | None = Field(default=None, alias="statusBadge")
    fields: list[DetailField] = Field(default_factory=list)
    breakdown: list[DetailBreakdown] = Field(default_factory=list)
    notes: str | None = None
    audit_trail: list[AuditTrailItem] = Field(default_factory=list, alias="auditTrail")
    model_config = _CAMEL


class ReportResponse(BaseModel):
    type: ReportType
    title: str
    period: ReportPeriod
    summary: list[ReportSummaryItem]
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    generated_at: ReportTime = Field(alias="generatedAt")
    metadata: dict[str, Any] = Field(default_factory=dict)
    model_config = _CAMEL
