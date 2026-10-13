"""Tenant-scoped report aggregation over the platform's authoritative ledgers."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.constants import DeliveryStatus
from app.modules.deliveries.models import DeliverySlip, DeliverySlipItem
from app.modules.expenses.models import Expense, ExpenseCategory
from app.modules.inventory.models import StockMovement
from app.modules.merchants.models import Merchant
from app.modules.orders.models import OrderStatusHistory
from app.modules.payments.models import Invoice, Payment
from app.modules.reports.constants import REPORT_TITLES, ReportType
from app.modules.reports.schemas import (
    AuditTrailItem,
    DetailBreakdown,
    DetailField,
    ReportColumn,
    ReportPeriod,
    ReportResponse,
    ReportRowDetail,
    ReportSummaryItem,
    StatusBadge,
)
from app.shared.business.actor import BusinessActor
from app.shared.date_time.business_calendar import IST_TIMEZONE, business_today
from app.shared.exceptions.api_error import ApiError

MAX_RANGE_DAYS = 3660
MAX_ROWS = 5000


@dataclass(frozen=True)
class ReportScope:
    """An explicit report data boundary.

    A missing merchant id is only valid when ``all_merchants`` is deliberately enabled by
    the Admin-channel router.  Keeping that decision in a value object prevents an omitted
    merchant id from accidentally turning a merchant request into a platform-wide query.
    """

    merchant_id: str | None
    all_merchants: bool = False

    def __post_init__(self) -> None:
        if self.all_merchants == (self.merchant_id is not None):
            raise ValueError("ReportScope must select one merchant or explicitly select all merchants")

    @classmethod
    def merchant(cls, actor: BusinessActor) -> "ReportScope":
        return cls(merchant_id=actor.require_merchant_id())

    @classmethod
    def admin(cls, merchant_id: str | None) -> "ReportScope":
        return cls(merchant_id=merchant_id, all_merchants=merchant_id is None)


def report_range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    """Validate an inclusive UTC query range using India business-day defaults."""
    today = business_today()
    start = date_from or datetime.combine(today, time.min, tzinfo=IST_TIMEZONE)
    end = date_to or datetime.combine(today, time.max, tzinfo=IST_TIMEZONE)
    start = _utc(start)
    end = _utc(end)
    if start > end:
        raise ApiError(
            "INVALID_DATE_RANGE",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "from must be earlier than or equal to to.",
        )
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise ApiError(
            "REPORT_RANGE_TOO_LARGE",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Report range cannot exceed {MAX_RANGE_DAYS} days.",
        )
    return start, end


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).astimezone(IST_TIMEZONE).isoformat(timespec="seconds")


def _day(value: date | datetime | None) -> str | None:
    return value.strftime("%d %b %Y") if value else None


def _money(value: Decimal | float | None) -> float:
    return float(value or 0)


def _badge(value: str) -> StatusBadge:
    color = {
        "DELIVERED": "success",
        "RECONCILED": "success",
        "PAID": "success",
        "INVALID": "danger",
        "FAILED": "danger",
        "CANCELLED": "danger",
        "PENDING": "warning",
        "PARTIALLY_PAID": "warning",
        "UNPAID": "warning",
    }.get(value.upper(), "info")
    return StatusBadge(label=value, color=color)


class ReportService:
    def __init__(self, session: AsyncSession, scope: ReportScope) -> None:
        self.session = session
        self.scope = scope
        self.merchant_id = scope.merchant_id
        self._merchant_names: dict[str, str] = {}

    async def build(
        self,
        report_type: ReportType,
        start: datetime,
        end: datetime,
        *,
        customer_id: str | None = None,
    ) -> ReportResponse:
        if self.scope.all_merchants:
            self._merchant_names = {
                merchant_id: name
                for merchant_id, name in await self.session.execute(
                    select(Merchant.id, Merchant.name)
                )
            }
        builders = {
            ReportType.DAILY_DELIVERY: self._deliveries,
            ReportType.PAYMENT_COLLECTION: self._payments,
            ReportType.PENDING_PICKUP: self._pending_pickups,
            ReportType.EXPENSE: self._expenses,
            ReportType.STOCK_MOVEMENT: self._stock,
            ReportType.PROFIT_LOSS: self._profit_loss,
            ReportType.TAX_GST: self._tax_gst,
        }
        summary, columns, rows, metadata = await builders[report_type](
            start, end, customer_id
        )
        return ReportResponse(
            type=report_type,
            title=REPORT_TITLES[report_type],
            period=ReportPeriod(**{"from": start, "to": end}),
            summary=[ReportSummaryItem(label=k, value=v) for k, v in summary],
            columns=[ReportColumn(**column) for column in columns],
            rows=rows,
            generatedAt=datetime.now(UTC),
            metadata={
                "rowCount": len(rows),
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "scope": "ALL_MERCHANTS" if self.scope.all_merchants else "MERCHANT",
                "merchantId": self.merchant_id,
                **metadata,
            },
        )

    async def _deliveries(self, start, end, customer_id):
        day_from, day_to = start.date(), end.date()
        filters = [
            *self._merchant_filter(DeliverySlip.merchant_id),
            DeliverySlip.scheduled_date.between(day_from, day_to),
        ]
        if customer_id:
            filters.append(DeliverySlip.customer_id == customer_id)
        slips = list(
            await self.session.scalars(
                select(DeliverySlip)
                .where(*filters)
                .order_by(DeliverySlip.scheduled_date.desc(), DeliverySlip.created_at.desc())
                .limit(MAX_ROWS + 1)
            )
        )
        truncated = len(slips) > MAX_ROWS
        slips = slips[:MAX_ROWS]
        items = await self._slip_items([row.id for row in slips])
        history = await self._order_history([row.order_id for row in slips])
        rows = []
        for slip in slips:
            lines = items.get(slip.id, [])
            quantity = sum((line.delivered_quantity if line.delivered_quantity is not None else line.quantity) for line in lines)
            trail = [
                AuditTrailItem(
                    action=f"Order status changed to {event.status}",
                    timestamp=event.changed_at,
                    user=event.changed_by_name or "System",
                )
                for event in history.get(slip.order_id, [])
            ]
            details = ReportRowDetail(
                id=slip.id,
                title=f"Slip {slip.slip_number}",
                subtitle=slip.customer_name,
                statusBadge=_badge(slip.status),
                fields=[
                    DetailField(label="Customer", value=slip.customer_name),
                    DetailField(label="Order", value=slip.order_number),
                    DetailField(label="Scheduled Date", value=_day(slip.scheduled_date)),
                    DetailField(label="Dispatched", value=_stamp(slip.dispatched_at)),
                    DetailField(label="Delivered", value=_stamp(slip.delivered_at)),
                    DetailField(label="Allocated Cylinders", value=slip.cylinders_allocated, highlight=True),
                    DetailField(label="Empties Collected", value=slip.empties_collected),
                    DetailField(label="Driver / Agent", value=f"{slip.driver_name} ({slip.vehicle_number})"),
                ],
                breakdown=[
                    DetailBreakdown(
                        title=line.cylinder_type,
                        quantity=line.delivered_quantity if line.delivered_quantity is not None else line.quantity,
                        subtitle="Delivered cylinders",
                    )
                    for line in lines
                ],
                notes=slip.note or f"Delivery location: {slip.delivery_site_name}",
                auditTrail=trail,
            )
            rows.append(
                {
                    "id": slip.id,
                    "displayId": slip.slip_number,
                    **self._merchant_fields(slip.merchant_id),
                    "customerId": slip.customer_id,
                    "slip": slip.slip_number,
                    "customer": slip.customer_name,
                    "qty": quantity,
                    "empties": slip.empties_collected,
                    "status": slip.status,
                    "scheduledDate": slip.scheduled_date.isoformat(),
                    "_details": details.model_dump(by_alias=True, mode="json"),
                }
            )
        return (
            [
                ("Deliveries", len(slips)),
                ("Delivered", sum(row.status == DeliveryStatus.DELIVERED.value for row in slips)),
                ("Cylinders", sum(row["qty"] for row in rows)),
                ("Empties collected", sum(row.empties_collected or 0 for row in slips)),
            ],
            self._columns(("slip", "Slip"), ("customer", "Customer"), ("qty", "Qty", "right"), ("empties", "Empties", "right"), ("status", "Status")),
            rows,
            {"truncated": truncated},
        )

    async def _payments(self, start, end, customer_id):
        filters = [*self._merchant_filter(Payment.merchant_id), Payment.paid_at.between(start, end)]
        if customer_id:
            filters.append(Payment.customer_id == customer_id)
        payments = list(
            await self.session.scalars(
                select(Payment).where(*filters).order_by(Payment.paid_at.desc()).limit(MAX_ROWS + 1)
            )
        )
        truncated = len(payments) > MAX_ROWS
        payments = payments[:MAX_ROWS]
        rows = []
        for payment in payments:
            detail = ReportRowDetail(
                id=payment.id,
                title=payment.payment_number,
                subtitle=payment.customer_name,
                statusBadge=_badge(payment.reconciliation_status),
                fields=[
                    DetailField(label="Invoice", value=payment.invoice_number),
                    DetailField(label="Invoice amount", value=payment.invoice_amount),
                    DetailField(label="Amount collected", value=payment.amount_collected, highlight=True),
                    DetailField(label="Payment mode", value=payment.mode),
                    DetailField(label="Transaction / UTR", value=payment.reference),
                    DetailField(label="Collected by", value=payment.collected_by_name),
                    DetailField(label="Customer running balance", value=payment.customer_running_balance),
                ],
                notes=payment.note or payment.invalid_reason,
                auditTrail=[
                    AuditTrailItem(action="Payment collected", timestamp=payment.paid_at, user=payment.collected_by_name),
                    *(
                        [AuditTrailItem(action=f"Payment {payment.reconciliation_status.lower()}", timestamp=payment.reconciled_at, user=payment.reconciled_by_name)]
                        if payment.reconciled_at else []
                    ),
                ],
            )
            rows.append({
                "id": payment.id,
                "displayId": payment.payment_number,
                **self._merchant_fields(payment.merchant_id),
                "customerId": payment.customer_id,
                "payment": payment.payment_number,
                "invoice": payment.invoice_number,
                "customer": payment.customer_name,
                "amount": payment.amount_collected,
                "mode": payment.mode,
                "reference": payment.reference,
                "status": payment.reconciliation_status,
                "paidAt": _stamp(payment.paid_at),
                "_details": detail.model_dump(by_alias=True, mode="json"),
            })
        valid = [p for p in payments if p.reconciliation_status != "INVALID"]
        return (
            [("Payments", len(payments)), ("Collected", sum(p.amount_collected for p in valid)), ("Pending", sum(p.reconciliation_status == "PENDING" for p in payments)), ("Reconciled", sum(p.reconciliation_status == "RECONCILED" for p in payments))],
            self._columns(("payment", "Payment"), ("invoice", "Invoice"), ("customer", "Customer"), ("amount", "Amount", "right"), ("mode", "Mode"), ("status", "Status")),
            rows,
            {"truncated": truncated},
        )

    async def _pending_pickups(self, start, end, customer_id):
        filters = [
            *self._merchant_filter(DeliverySlip.merchant_id),
            DeliverySlip.status == DeliveryStatus.DELIVERED.value,
            DeliverySlip.delivered_at.between(start, end),
        ]
        if customer_id:
            filters.append(DeliverySlip.customer_id == customer_id)
        slips = list(await self.session.scalars(select(DeliverySlip).where(*filters).order_by(DeliverySlip.delivered_at.desc()).limit(MAX_ROWS + 1)))
        truncated = len(slips) > MAX_ROWS
        slips = slips[:MAX_ROWS]
        items = await self._slip_items([s.id for s in slips])
        rows = []
        for slip in slips:
            delivered = sum(i.delivered_quantity if i.delivered_quantity is not None else i.quantity for i in items.get(slip.id, []))
            pending = max(delivered - (slip.empties_collected or 0), 0)
            if not pending:
                continue
            rows.append({
                "id": slip.id,
                "displayId": slip.slip_number,
                **self._merchant_fields(slip.merchant_id),
                "customerId": slip.customer_id,
                "customer": slip.customer_name,
                "slip": slip.slip_number,
                "delivered": delivered,
                "returned": slip.empties_collected or 0,
                "pending": pending,
                "since": _stamp(slip.delivered_at),
                "_details": ReportRowDetail(
                    id=slip.id,
                    title=f"Pending empties - {slip.customer_name}",
                    subtitle=slip.slip_number,
                    statusBadge=StatusBadge(label="PENDING", color="warning"),
                    fields=[DetailField(label="Delivered", value=delivered), DetailField(label="Returned", value=slip.empties_collected or 0), DetailField(label="Pending pickup", value=pending, highlight=True)],
                    notes=slip.delivery_site_name,
                ).model_dump(by_alias=True, mode="json"),
            })
        return (
            [("Customers / slips", len(rows)), ("Pending empties", sum(r["pending"] for r in rows)), ("Returned", sum(r["returned"] for r in rows))],
            self._columns(("customer", "Customer"), ("slip", "Slip"), ("delivered", "Delivered", "right"), ("returned", "Returned", "right"), ("pending", "Pending", "right"), ("since", "Since")),
            rows,
            {"truncated": truncated, "basis": "Delivered cylinders minus empties collected per slip"},
        )

    async def _expenses(self, start, end, customer_id):
        self._reject_customer_filter(customer_id, ReportType.EXPENSE)
        result = await self.session.execute(
            select(Expense, ExpenseCategory)
            .join(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
            .where(*self._merchant_filter(Expense.merchant_id), Expense.spent_on.between(start.date(), end.date()))
            .order_by(Expense.spent_on.desc(), Expense.created_at.desc())
            .limit(MAX_ROWS + 1)
        )
        records = list(result.all())
        truncated = len(records) > MAX_ROWS
        records = records[:MAX_ROWS]
        by_category: dict[str, Decimal] = defaultdict(Decimal)
        rows = []
        for expense, category in records:
            by_category[category.label] += expense.amount
            rows.append({
                "id": expense.id,
                "displayId": f"{category.label} - {_day(expense.spent_on)}",
                **self._merchant_fields(expense.merchant_id),
                "date": expense.spent_on.isoformat(),
                "category": category.label,
                "amount": _money(expense.amount),
                "note": expense.note,
                "recordedBy": expense.recorded_by_name,
                "_details": ReportRowDetail(
                    id=expense.id,
                    title=category.label,
                    subtitle=_day(expense.spent_on),
                    fields=[DetailField(label="Amount", value=_money(expense.amount), highlight=True), DetailField(label="Recorded by", value=expense.recorded_by_name)],
                    notes=expense.note,
                    auditTrail=[AuditTrailItem(action="Expense recorded", timestamp=expense.created_at, user=expense.recorded_by_name)],
                ).model_dump(by_alias=True, mode="json"),
            })
        return (
            [("Expenses", len(rows)), ("Total overhead", _money(sum((e.amount for e, _ in records), Decimal()))), ("Categories", len(by_category))],
            self._columns(("date", "Date"), ("category", "Category"), ("amount", "Amount", "right"), ("note", "Note"), ("recordedBy", "Recorded By")),
            rows,
            {"truncated": truncated, "categoryTotals": {k: _money(v) for k, v in by_category.items()}},
        )

    async def _stock(self, start, end, customer_id):
        self._reject_customer_filter(customer_id, ReportType.STOCK_MOVEMENT)
        movements = list(await self.session.scalars(
            select(StockMovement).where(*self._merchant_filter(StockMovement.merchant_id), StockMovement.recorded_at.between(start, end)).order_by(StockMovement.recorded_at.desc()).limit(MAX_ROWS + 1)
        ))
        truncated = len(movements) > MAX_ROWS
        movements = movements[:MAX_ROWS]
        references = await self._stock_reference_labels(movements)
        rows = []
        for movement in movements:
            reference = references.get(movement.reference_id, movement.reference_id)
            rows.append({
                "id": movement.id,
                "displayId": reference or f"{movement.movement_type} - {movement.cylinder_type}",
                **self._merchant_fields(movement.merchant_id),
                "date": _stamp(movement.recorded_at),
                "type": movement.movement_type,
                "cylinderType": movement.cylinder_type,
                "quantity": movement.quantity,
                "filledDelta": movement.delta_filled,
                "emptyDelta": movement.delta_empty,
                "reference": reference,
                "referenceId": movement.reference_id,
                "recordedBy": movement.recorded_by_name,
                "_details": ReportRowDetail(
                    id=movement.id,
                    title=f"{movement.movement_type} - {movement.cylinder_type}",
                    subtitle=reference,
                    fields=[DetailField(label="Quantity", value=movement.quantity, highlight=True), DetailField(label="Filled delta", value=movement.delta_filled), DetailField(label="Empty delta", value=movement.delta_empty), DetailField(label="Damaged delta", value=movement.delta_damaged), DetailField(label="Reference type", value=movement.reference_type), DetailField(label="Recorded by", value=movement.recorded_by_name)],
                    notes=movement.note,
                    auditTrail=[AuditTrailItem(action="Stock movement recorded", timestamp=movement.recorded_at, user=movement.recorded_by_name)],
                ).model_dump(by_alias=True, mode="json"),
            })
        return (
            [("Movements", len(rows)), ("Units moved", sum(m.quantity for m in movements)), ("Filled net", sum(m.delta_filled for m in movements)), ("Empty net", sum(m.delta_empty for m in movements))],
            self._columns(("date", "Date"), ("type", "Movement"), ("cylinderType", "Cylinder"), ("quantity", "Quantity", "right"), ("reference", "Reference"), ("recordedBy", "Recorded By")),
            rows,
            {"truncated": truncated},
        )

    async def _profit_loss(self, start, end, customer_id):
        self._reject_customer_filter(customer_id, ReportType.PROFIT_LOSS)
        if self.scope.all_merchants:
            return await self._global_profit_loss(start, end)
        revenue = await self.session.scalar(select(func.coalesce(func.sum(Invoice.amount), 0)).where(*self._merchant_filter(Invoice.merchant_id), Invoice.issued_at.between(start, end)))
        expenses = await self.session.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*self._merchant_filter(Expense.merchant_id), Expense.spent_on.between(start.date(), end.date())))
        revenue_value, expense_value = _money(revenue), _money(expenses)
        net = revenue_value - expense_value
        rows = [
            {"id": "revenue", "displayId": "Revenue (taxable sales)", "category": "Revenue (taxable sales)", "amount": revenue_value, "kind": "INCOME", "_details": None},
            {"id": "expenses", "displayId": "Operating expenses", "category": "Operating expenses", "amount": expense_value, "kind": "EXPENSE", "_details": None},
            {"id": "net", "displayId": "Net operating profit", "category": "Net operating profit", "amount": net, "kind": "PROFIT" if net >= 0 else "LOSS", "_details": None},
        ]
        return (
            [("Revenue", revenue_value), ("Operating overhead", expense_value), ("Net profit / loss", net)],
            self._columns(("category", "Category"), ("kind", "Type"), ("amount", "Amount", "right")),
            rows,
            {"accountingBasis": "Invoice taxable amount minus recorded operating expenses; GST excluded from revenue"},
        )

    async def _tax_gst(self, start, end, customer_id):
        filters = [*self._merchant_filter(Invoice.merchant_id), Invoice.issued_at.between(start, end)]
        if customer_id:
            filters.append(Invoice.customer_id == customer_id)
        invoices = list(await self.session.scalars(select(Invoice).where(*filters).order_by(Invoice.issued_at.desc()).limit(MAX_ROWS + 1)))
        truncated = len(invoices) > MAX_ROWS
        invoices = invoices[:MAX_ROWS]
        rows = [{
            "id": invoice.id,
            "displayId": invoice.invoice_number,
            **self._merchant_fields(invoice.merchant_id),
            "customerId": invoice.customer_id,
            "invoice": invoice.invoice_number,
            "customer": invoice.customer_name,
            "taxableValue": invoice.amount,
            "gstPercent": invoice.gst_percent,
            "outwardGst": invoice.gst_amount,
            "total": invoice.total_amount,
            "issuedAt": _stamp(invoice.issued_at),
            "gstin": invoice.gstin,
            "_details": ReportRowDetail(id=invoice.id, title=invoice.invoice_number, subtitle=invoice.customer_name, fields=[DetailField(label="Taxable value", value=invoice.amount), DetailField(label="GST rate", value=f"{invoice.gst_percent}%"), DetailField(label="Outward GST", value=invoice.gst_amount, highlight=True), DetailField(label="Invoice total", value=invoice.total_amount), DetailField(label="GSTIN", value=invoice.gstin)]).model_dump(by_alias=True, mode="json"),
        } for invoice in invoices]
        outward = sum(i.gst_amount for i in invoices)
        return (
            [("Tax invoices", len(invoices)), ("Taxable sales", sum(i.amount for i in invoices)), ("Outward GST", outward), ("Recorded input ITC", 0), ("Net GST liability", outward)],
            self._columns(("invoice", "Invoice"), ("customer", "Customer"), ("taxableValue", "Taxable Value", "right"), ("gstPercent", "GST %", "right"), ("outwardGst", "Outward GST", "right"), ("total", "Total", "right")),
            rows,
            {"truncated": truncated, "inputItcStatus": "NOT_RECORDED", "warning": "Expense records do not currently capture GST input tax. ITC is not inferred from gross expense amounts."},
        )

    async def _global_profit_loss(self, start, end):
        revenue_rows = (
            await self.session.execute(
                select(Invoice.merchant_id, func.coalesce(func.sum(Invoice.amount), 0))
                .where(Invoice.issued_at.between(start, end))
                .group_by(Invoice.merchant_id)
            )
        ).all()
        expense_rows = (
            await self.session.execute(
                select(Expense.merchant_id, func.coalesce(func.sum(Expense.amount), 0))
                .where(Expense.spent_on.between(start.date(), end.date()))
                .group_by(Expense.merchant_id)
            )
        ).all()
        revenue_by_merchant = {merchant_id: _money(amount) for merchant_id, amount in revenue_rows}
        expense_by_merchant = {merchant_id: _money(amount) for merchant_id, amount in expense_rows}
        merchant_ids = sorted(
            revenue_by_merchant.keys() | expense_by_merchant.keys(),
            key=lambda value: self._merchant_names.get(value, value),
        )
        rows = []
        for merchant_id in merchant_ids[:MAX_ROWS]:
            revenue = revenue_by_merchant.get(merchant_id, 0.0)
            expenses = expense_by_merchant.get(merchant_id, 0.0)
            net = revenue - expenses
            rows.append(
                {
                    "id": merchant_id,
                    "displayId": self._merchant_names.get(merchant_id, merchant_id),
                    **self._merchant_fields(merchant_id),
                    "revenue": revenue,
                    "expenses": expenses,
                    "netProfit": net,
                    "status": "PROFIT" if net >= 0 else "LOSS",
                    "_details": None,
                }
            )
        total_revenue = sum(revenue_by_merchant.values())
        total_expenses = sum(expense_by_merchant.values())
        return (
            [
                ("Revenue", total_revenue),
                ("Operating overhead", total_expenses),
                ("Net profit / loss", total_revenue - total_expenses),
            ],
            self._columns(
                ("revenue", "Revenue", "right"),
                ("expenses", "Expenses", "right"),
                ("netProfit", "Net Profit / Loss", "right"),
                ("status", "Status"),
            ),
            rows,
            {
                "truncated": len(merchant_ids) > MAX_ROWS,
                "accountingBasis": "Invoice taxable amount minus recorded operating expenses; GST excluded from revenue",
            },
        )

    async def _slip_items(self, slip_ids: list[str]) -> dict[str, list[DeliverySlipItem]]:
        if not slip_ids:
            return {}
        grouped: dict[str, list[DeliverySlipItem]] = defaultdict(list)
        for item in await self.session.scalars(select(DeliverySlipItem).where(DeliverySlipItem.slip_id.in_(slip_ids)).order_by(DeliverySlipItem.position)):
            grouped[item.slip_id].append(item)
        return grouped

    async def _order_history(self, order_ids: list[str]) -> dict[str, list[OrderStatusHistory]]:
        if not order_ids:
            return {}
        grouped: dict[str, list[OrderStatusHistory]] = defaultdict(list)
        for event in await self.session.scalars(select(OrderStatusHistory).where(OrderStatusHistory.order_id.in_(order_ids)).order_by(OrderStatusHistory.changed_at)):
            grouped[event.order_id].append(event)
        return grouped

    async def _stock_reference_labels(
        self, movements: list[StockMovement]
    ) -> dict[str, str]:
        """Resolve delivery UUID ledger references to the slip number staff recognise."""
        delivery_ids = {
            movement.reference_id
            for movement in movements
            if movement.reference_type == "DELIVERY" and movement.reference_id
        }
        if not delivery_ids:
            return {}
        return {
            slip_id: slip_number
            for slip_id, slip_number in await self.session.execute(
                select(DeliverySlip.id, DeliverySlip.slip_number).where(
                    DeliverySlip.id.in_(delivery_ids)
                )
            )
        }

    def _merchant_filter(self, column):
        return [] if self.scope.all_merchants else [column == self.merchant_id]

    def _merchant_fields(self, merchant_id: str) -> dict[str, str]:
        if not self.scope.all_merchants:
            return {}
        return {
            "merchantId": merchant_id,
            "merchant": self._merchant_names.get(merchant_id, merchant_id),
        }

    def _columns(self, *definitions):
        columns = [
            {"key": value[0], "label": value[1], "align": value[2] if len(value) > 2 else "left"}
            for value in definitions
        ]
        if self.scope.all_merchants:
            return [
                {"key": "merchant", "label": "Merchant", "align": "left"},
                *columns,
            ]
        return columns

    @staticmethod
    def _reject_customer_filter(customer_id: str | None, report_type: ReportType) -> None:
        if customer_id:
            raise ApiError("FILTER_NOT_SUPPORTED", status.HTTP_422_UNPROCESSABLE_CONTENT, f"customerId is not supported for {report_type.value}.")
