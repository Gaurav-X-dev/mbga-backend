"""Read-only receivables reporting over invoice balances and payment allocations."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, case, func, or_, select

from app.modules.customers.models import (
    CustomerProfile,
    CustomerReportGroup,
    CustomerReportMembership,
)
from app.modules.merchants.models import Merchant
from app.modules.payments.models import Invoice, Payment
from app.modules.reports.constants import REPORT_TITLES, ReportType
from app.modules.reports.schemas import ReportResponse
from app.shared.date_time.business_calendar import IST_TIMEZONE, business_today
from app.shared.exceptions.api_error import ApiError


class ReceivableFilters(BaseModel):
    type: Literal["OUTSTANDING_DUES", "CUSTOMER_COLLECTION"] = "OUTSTANDING_DUES"
    merchant_id: str | None = Field(default=None, alias="merchantId", max_length=36)
    customer_id: str | None = Field(default=None, alias="customerId", max_length=36)
    group_id: str | None = Field(default=None, alias="groupId", max_length=36)
    group_by: Literal["customer", "group"] = Field(default="customer", alias="groupBy")
    search: str = Field(default="", max_length=160)
    customer_type: str | None = Field(default=None, alias="customerType", max_length=40)
    city: str | None = Field(default=None, max_length=120)
    overdue_only: bool = Field(default=False, alias="overdueOnly")
    min_amount: int = Field(default=0, alias="minAmount", ge=0)
    date_from: date | None = Field(default=None, alias="dateFrom")
    date_to: date | None = Field(default=None, alias="dateTo")
    mode: Literal["CASH", "UPI", "SPLIT", "NEFT"] | None = None
    status: Literal["PENDING", "RECONCILED", "INVALID"] | None = None
    collector: str | None = Field(default=None, max_length=36)
    sort_by: Literal["amount", "name"] = Field(default="amount", alias="sortBy")
    direction: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=1000000)

    @model_validator(mode="after")
    def dates(self):
        today = business_today()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("From must be on or before To.")
        if any(day and day > today for day in (self.date_from, self.date_to)):
            raise ValueError("Future report dates are not supported.")
        if self.type == "OUTSTANDING_DUES" and (self.date_from or self.date_to):
            raise ValueError(
                "Outstanding dues shows current balances; historical dates are not supported."
            )
        return self

    @property
    def window(self):
        today = business_today()
        end = self.date_to or today
        start = self.date_from or (end - timedelta(days=29))
        return (
            datetime.combine(start, time.min, IST_TIMEZONE).astimezone(UTC),
            datetime.combine(end + timedelta(days=1), time.min, IST_TIMEZONE).astimezone(UTC),
        )


def _sum_if(condition, value):
    return func.sum(case((condition, value), else_=0))


def payment_filters(f):
    start, end = f.window
    clauses = [Payment.paid_at >= start, Payment.paid_at < end, Payment.mode != "ADVANCE"]
    for column, value in [
        (Payment.merchant_id, f.merchant_id),
        (Payment.customer_id, f.customer_id),
        (Payment.mode, f.mode),
        (Payment.reconciliation_status, f.status),
        (Payment.collected_by_user_id, f.collector),
    ]:
        if value:
            clauses.append(column == value)
    return clauses


def payment_amounts():
    # Split payments can already have cash applied while the UPI portion awaits verification.
    valid = Payment.reconciliation_status != "INVALID"
    pending = and_(
        Payment.reconciliation_status == "PENDING",
        Payment.amount_collected > Payment.applied_amount,
    )
    return [
        _sum_if(valid, Payment.applied_amount).label("appliedAmount"),
        _sum_if(pending, Payment.amount_collected - Payment.applied_amount).label("pendingAmount"),
        _sum_if(Payment.reconciliation_status == "INVALID", Payment.amount_collected).label(
            "invalidAmount"
        ),
    ]


class ReceivablesService:
    def __init__(self, session):
        self.session = session

    async def validate_scope(self, f):
        if f.merchant_id and await self.session.get(Merchant, f.merchant_id) is None:
            raise ApiError("MERCHANT_NOT_FOUND", 404, "The selected merchant does not exist.")
        if f.customer_id:
            customer = await self.session.get(CustomerProfile, f.customer_id)
            if customer is None or (f.merchant_id and customer.merchant_id != f.merchant_id):
                raise ApiError(
                    "CUSTOMER_NOT_FOUND", 404, "The customer does not belong to this merchant."
                )
        if f.group_id and f.group_id != "ungrouped":
            group = await self.session.get(CustomerReportGroup, f.group_id)
            if group is None or (f.merchant_id and group.merchant_id != f.merchant_id):
                raise ApiError(
                    "GROUP_NOT_FOUND", 404, "The group does not belong to this merchant."
                )

    def customer_query(self, f):
        today = business_today()
        midnight = datetime.combine(today, time.min, IST_TIMEZONE).astimezone(UTC)
        invoice_filters = [Invoice.balance > 0]
        if f.merchant_id:
            invoice_filters.append(Invoice.merchant_id == f.merchant_id)
        if f.customer_id:
            invoice_filters.append(Invoice.customer_id == f.customer_id)

        def overdue_between(low, high=None):
            upper = midnight - timedelta(days=low - 1)
            cond = Invoice.due_at < upper
            if high is not None:
                cond = and_(cond, Invoice.due_at >= midnight - timedelta(days=high))
            return cond

        invoices = (
            select(
                Invoice.customer_id,
                Invoice.merchant_id,
                func.sum(Invoice.balance).label("outstanding"),
                func.count().label("invoiceCount"),
                func.min(Invoice.due_at).label("oldestDueAt"),
                _sum_if(Invoice.due_at >= midnight, Invoice.balance).label("notDueAmount"),
                _sum_if(Invoice.due_at < midnight, Invoice.balance).label("overdueAmount"),
                _sum_if(overdue_between(1, 30), Invoice.balance).label("age30Amount"),
                _sum_if(overdue_between(31, 60), Invoice.balance).label("age60Amount"),
                _sum_if(overdue_between(61, 90), Invoice.balance).label("age90Amount"),
                _sum_if(overdue_between(91), Invoice.balance).label("ageOver90Amount"),
            )
            .where(*invoice_filters)
            .group_by(Invoice.customer_id, Invoice.merchant_id)
            .subquery()
        )
        clauses = (
            payment_filters(f)
            if f.type == "CUSTOMER_COLLECTION"
            else [
                Payment.reconciliation_status == "PENDING",
                Payment.amount_collected > Payment.applied_amount,
            ]
        )
        if f.type == "OUTSTANDING_DUES" and f.merchant_id:
            clauses.append(Payment.merchant_id == f.merchant_id)
        payments = (
            select(
                Payment.customer_id,
                Payment.merchant_id,
                *payment_amounts(),
                func.count(func.distinct(func.coalesce(Payment.collection_id, Payment.id))).label(
                    "receiptCount"
                ),
            )
            .where(*clauses)
            .group_by(Payment.customer_id, Payment.merchant_id)
            .subquery()
        )
        money_keys = [
            "outstanding",
            "notDueAmount",
            "overdueAmount",
            "age30Amount",
            "age60Amount",
            "age90Amount",
            "ageOver90Amount",
        ]
        query = (
            select(
                CustomerProfile.id.label("customerId"),
                CustomerProfile.merchant_id.label("merchantId"),
                func.coalesce(
                    CustomerProfile.name, CustomerProfile.owner_name, CustomerProfile.mobile_number
                ).label("customer"),
                CustomerProfile.mobile_number.label("mobile"),
                Merchant.name.label("merchant"),
                CustomerReportGroup.id.label("groupId"),
                func.coalesce(CustomerReportGroup.name, "Ungrouped").label("group"),
                *(
                    [
                        func.coalesce(invoices.c[key], 0).label(key)
                        for key in [*money_keys, "invoiceCount"]
                    ]
                    + [invoices.c.oldestDueAt]
                    if f.type == "OUTSTANDING_DUES"
                    else []
                ),
                *[
                    func.coalesce(payments.c[key], 0).label(key)
                    for key in ["appliedAmount", "pendingAmount", "invalidAmount", "receiptCount"]
                ],
            )
            .join(Merchant, Merchant.id == CustomerProfile.merchant_id)
            .outerjoin(
                CustomerReportMembership, CustomerReportMembership.customer_id == CustomerProfile.id
            )
            .outerjoin(
                CustomerReportGroup,
                and_(
                    CustomerReportGroup.id == CustomerReportMembership.group_id,
                    CustomerReportGroup.merchant_id == CustomerProfile.merchant_id,
                ),
            )
            .outerjoin(
                payments,
                and_(
                    payments.c.customer_id == CustomerProfile.id,
                    payments.c.merchant_id == CustomerProfile.merchant_id,
                ),
            )
        )
        if f.type == "OUTSTANDING_DUES":
            query = query.outerjoin(
                invoices,
                and_(
                    invoices.c.customer_id == CustomerProfile.id,
                    invoices.c.merchant_id == CustomerProfile.merchant_id,
                ),
            )
        if f.merchant_id:
            query = query.where(CustomerProfile.merchant_id == f.merchant_id)
        if f.customer_id:
            query = query.where(CustomerProfile.id == f.customer_id)
        if f.group_id:
            query = query.where(
                CustomerReportGroup.id.is_(None)
                if f.group_id == "ungrouped"
                else CustomerReportGroup.id == f.group_id
            )
        if f.customer_type:
            query = query.where(CustomerProfile.customer_type == f.customer_type)
        if f.city:
            query = query.where(CustomerProfile.address_city == f.city)
        if f.search.strip():
            term = (
                "%"
                + f.search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            query = query.where(
                or_(
                    *[
                        c.ilike(term, escape="\\")
                        for c in [
                            CustomerProfile.name,
                            CustomerProfile.owner_name,
                            CustomerProfile.mobile_number,
                            CustomerProfile.code,
                        ]
                    ]
                )
            )
        if f.type == "OUTSTANDING_DUES":
            query = query.where(invoices.c.outstanding > 0, invoices.c.outstanding >= f.min_amount)
            if f.overdue_only:
                query = query.where(invoices.c.overdueAmount > 0)
        else:
            query = query.where(
                payments.c.receiptCount > 0,
                payments.c.appliedAmount + payments.c.pendingAmount + payments.c.invalidAmount
                >= f.min_amount,
            )
        return query

    async def build(self, f, *, export=False):
        await self.validate_scope(f)
        base = self.customer_query(f).subquery()
        amount_keys = (
            [
                "outstanding",
                "notDueAmount",
                "overdueAmount",
                "age30Amount",
                "age60Amount",
                "age90Amount",
                "ageOver90Amount",
                "pendingAmount",
            ]
            if f.type == "OUTSTANDING_DUES"
            else ["appliedAmount", "pendingAmount", "invalidAmount"]
        )
        totals = (
            (
                await self.session.execute(
                    select(
                        func.count().label("customerCount"),
                        *[
                            func.coalesce(func.sum(base.c[key]), 0).label(key)
                            for key in amount_keys
                        ],
                    )
                )
            )
            .mappings()
            .one()
        )
        if f.group_by == "group":
            query = select(
                base.c.merchantId,
                base.c.merchant,
                base.c.groupId,
                base.c.group,
                func.count().label("customerCount"),
                *[func.sum(base.c[key]).label(key) for key in amount_keys],
            ).group_by(base.c.merchantId, base.c.merchant, base.c.groupId, base.c.group)
        else:
            query = select(base)
        table = query.subquery()
        total = await self.session.scalar(select(func.count()).select_from(table))
        sort_key = (
            ("group" if f.group_by == "group" else "customer")
            if f.sort_by == "name"
            else ("outstanding" if f.type == "OUTSTANDING_DUES" else "appliedAmount")
        )
        order = table.c[sort_key].asc() if f.direction == "asc" else table.c[sort_key].desc()
        query = select(table).order_by(
            order,
            table.c.merchantId,
            table.c.groupId if f.group_by == "group" else table.c.customerId,
        )
        if export and total > 10000:
            raise ApiError(
                "REPORT_EXPORT_LIMIT",
                422,
                "More than 10,000 rows. Narrow the filters before exporting.",
            )
        records = (
            (
                await self.session.execute(
                    query.limit(10000 if export else f.limit).offset(0 if export else f.offset)
                )
            )
            .mappings()
            .all()
        )
        rows = []
        for record in records:
            row = dict(record)
            row["id"] = (
                f"{row['merchantId']}:{row.get('customerId') or row.get('groupId') or 'ungrouped'}"
            )
            for key, value in row.items():
                if key.endswith("Amount") or key in (
                    "outstanding",
                    "invoiceCount",
                    "receiptCount",
                    "customerCount",
                ):
                    row[key] = int(value or 0)
                elif isinstance(value, datetime):
                    row[key] = (
                        (value.replace(tzinfo=UTC) if value.tzinfo is None else value)
                        .astimezone(IST_TIMEZONE)
                        .isoformat()
                    )
            rows.append(row)
        labels = {
            "outstanding": "Outstanding amount",
            "notDueAmount": "Not yet due amount",
            "overdueAmount": "Overdue amount",
            "age30Amount": "1–30 days amount",
            "age60Amount": "31–60 days amount",
            "age90Amount": "61–90 days amount",
            "ageOver90Amount": "90+ days amount",
            "pendingAmount": "Pending verification amount",
            "appliedAmount": "Applied collections amount",
            "invalidAmount": "Invalid submissions amount",
        }
        columns = [("merchant", "Merchant"), ("group", "Group")]
        columns += (
            [("customerCount", "Customers")]
            if f.group_by == "group"
            else [("customer", "Customer"), ("mobile", "Mobile")]
        )
        columns += [(key, labels[key]) for key in amount_keys]
        if f.type == "OUTSTANDING_DUES" and f.group_by == "customer":
            columns += [("oldestDueAt", "Oldest due date")]
        start, end = f.window
        if f.type == "OUTSTANDING_DUES":
            start = datetime.combine(business_today(), time.min, IST_TIMEZONE)
            end = datetime.now(UTC)
        collectors = []
        if f.type == "CUSTOMER_COLLECTION":
            options = select(
                Payment.collected_by_user_id, func.max(Payment.collected_by_name)
            ).where(
                Payment.collected_by_user_id.is_not(None),
                Payment.paid_at >= start,
                Payment.paid_at < end,
            )
            if f.merchant_id:
                options = options.where(Payment.merchant_id == f.merchant_id)
            collectors = [
                {"value": user_id, "label": name or user_id}
                for user_id, name in (
                    await self.session.execute(
                        options.group_by(Payment.collected_by_user_id)
                        .order_by(func.max(Payment.collected_by_name), Payment.collected_by_user_id)
                        .limit(500)
                    )
                ).all()
            ]
        return ReportResponse(
            type=f.type,
            title=REPORT_TITLES[ReportType(f.type)],
            period={"from": start, "to": end - timedelta(microseconds=1)},
            summary=[
                {"label": "Customers", "value": totals["customerCount"]},
                *[
                    {"label": labels[k], "value": int(totals[k])}
                    for k in amount_keys
                    if not k.startswith("age")
                ],
            ],
            columns=[
                {
                    "key": key,
                    "label": label,
                    "align": "right" if key in amount_keys or key == "customerCount" else "left",
                }
                for key, label in columns
            ],
            rows=rows,
            generatedAt=datetime.now(UTC),
            metadata={
                "total": total,
                "limit": f.limit,
                "offset": f.offset,
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "balanceBasis": "CURRENT",
                "groupingBasis": "CURRENT_MEMBERSHIP",
                "collectionBasis": "PAYMENT_RECEIVED_DATE_CURRENT_RECONCILIATION",
                "collectors": collectors,
            },
        )

    async def detail(self, f):
        await self.validate_scope(f)
        if not f.customer_id:
            raise ApiError("CUSTOMER_REQUIRED", 422, "Select a customer.")
        if f.type == "OUTSTANDING_DUES":
            query = select(Invoice).where(Invoice.customer_id == f.customer_id, Invoice.balance > 0)
            if f.merchant_id:
                query = query.where(Invoice.merchant_id == f.merchant_id)
            total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
            invoices = (
                await self.session.scalars(
                    query.order_by(Invoice.due_at, Invoice.id).limit(f.limit).offset(f.offset)
                )
            ).all()
            ids = [i.id for i in invoices]
            payments = (
                (
                    await self.session.scalars(
                        select(Payment)
                        .where(Payment.invoice_id.in_(ids))
                        .order_by(Payment.paid_at, Payment.id)
                    )
                ).all()
                if ids
                else []
            )
            rows = []
            for invoice in invoices:
                rows.append(
                    {
                        "id": invoice.id,
                        "invoice": invoice.invoice_number,
                        "issuedAt": _stamp(invoice.issued_at),
                        "dueAt": _stamp(invoice.due_at),
                        "amount": invoice.total_amount,
                        "appliedAmount": invoice.paid_amount,
                        "balance": invoice.balance,
                        "_details": {
                            "id": invoice.id,
                            "title": invoice.invoice_number,
                            "fields": [
                                {"label": "Billed amount", "value": invoice.total_amount},
                                {"label": "Applied amount", "value": invoice.paid_amount},
                                {"label": "Outstanding amount", "value": invoice.balance},
                            ],
                            "auditTrail": [
                                {
                                    "action": f"{p.payment_number}: {p.mode}, {p.reconciliation_status}; collected {p.amount_collected}, applied {p.applied_amount}",
                                    "timestamp": _stamp(p.paid_at),
                                    "user": p.collected_by_name,
                                }
                                for p in payments
                                if p.invoice_id == invoice.id
                            ],
                        },
                    }
                )
        else:
            receipt_key = func.coalesce(Payment.collection_id, Payment.id)
            query = (
                select(
                    receipt_key.label("id"),
                    func.min(Payment.paid_at).label("paidAt"),
                    func.min(Payment.mode).label("mode"),
                    func.min(Payment.reference).label("reference"),
                    func.min(Payment.collected_by_name).label("collector"),
                    *payment_amounts(),
                )
                .where(*payment_filters(f))
                .group_by(receipt_key)
            )
            total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
            receipts = (
                (
                    await self.session.execute(
                        query.order_by(func.min(Payment.paid_at).desc(), receipt_key)
                        .limit(f.limit)
                        .offset(f.offset)
                    )
                )
                .mappings()
                .all()
            )
            ids = [r["id"] for r in receipts]
            parts = (
                (
                    await self.session.scalars(
                        select(Payment)
                        .where(*payment_filters(f), receipt_key.in_(ids))
                        .order_by(Payment.invoice_number, Payment.id)
                    )
                ).all()
                if ids
                else []
            )
            rows = []
            for receipt in receipts:
                row = dict(receipt)
                row["paidAt"] = _stamp(row["paidAt"])
                for key in ("appliedAmount", "pendingAmount", "invalidAmount"):
                    row[key] = int(row[key] or 0)
                allocations = [p for p in parts if (p.collection_id or p.id) == row["id"]]
                row["_details"] = {
                    "title": "Payment receipt",
                    "fields": [
                        {"label": "Reference", "value": row["reference"]},
                        {"label": "Collected by", "value": row["collector"]},
                        {"label": "Applied amount", "value": row["appliedAmount"]},
                        {"label": "Pending amount", "value": row["pendingAmount"]},
                    ],
                    "breakdown": [
                        {
                            "title": p.invoice_number,
                            "amount": p.amount_collected,
                            "subtitle": f"{p.reconciliation_status}; applied {p.applied_amount}",
                        }
                        for p in allocations
                    ],
                }
                rows.append(row)
        return {"rows": rows, "total": total}


def _stamp(value):
    return (
        (value.replace(tzinfo=UTC) if value.tzinfo is None else value)
        .astimezone(IST_TIMEZONE)
        .isoformat()
    )
