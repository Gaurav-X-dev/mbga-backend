from enum import StrEnum


class ReportType(StrEnum):
    DAILY_DELIVERY = "DAILY_DELIVERY"
    PAYMENT_COLLECTION = "PAYMENT_COLLECTION"
    PENDING_PICKUP = "PENDING_PICKUP"
    EXPENSE = "EXPENSE"
    STOCK_MOVEMENT = "STOCK_MOVEMENT"
    PROFIT_LOSS = "PROFIT_LOSS"
    TAX_GST = "TAX_GST"


class ExportFormat(StrEnum):
    CSV = "CSV"
    EXCEL = "EXCEL"
    XLSX = "XLSX"
    XML = "XML"
    XAML = "XAML"
    JSON = "JSON"


REPORT_TITLES = {
    ReportType.DAILY_DELIVERY: "Daily Delivery Report",
    ReportType.PAYMENT_COLLECTION: "Payment Collection Report",
    ReportType.PENDING_PICKUP: "Pending Empty Pickup Report",
    ReportType.EXPENSE: "Expense Report",
    ReportType.STOCK_MOVEMENT: "Stock Movement Report",
    ReportType.PROFIT_LOSS: "Profit & Loss Statement",
    ReportType.TAX_GST: "GST Tax Report",
}

FINANCIAL_REPORTS = frozenset(
    {ReportType.EXPENSE, ReportType.PROFIT_LOSS}
)
