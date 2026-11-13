from enum import StrEnum


class ReportType(StrEnum):
    VEHICLE_DISPATCH_RETURN = "VEHICLE_DISPATCH_RETURN"
    OUTSTANDING_DUES = "OUTSTANDING_DUES"
    CUSTOMER_COLLECTION = "CUSTOMER_COLLECTION"
    DAILY_DELIVERY = "DAILY_DELIVERY"
    PAYMENT_COLLECTION = "PAYMENT_COLLECTION"
    PENDING_PICKUP = "PENDING_PICKUP"
    EXPENSE = "EXPENSE"
    FUEL = "FUEL"
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
    ReportType.VEHICLE_DISPATCH_RETURN: "Vehicle Dispatch & Returns",
    ReportType.OUTSTANDING_DUES: "Outstanding Dues",
    ReportType.CUSTOMER_COLLECTION: "Customer Collections",
    ReportType.DAILY_DELIVERY: "Daily Delivery Report",
    ReportType.PAYMENT_COLLECTION: "Payment Collection Report",
    ReportType.PENDING_PICKUP: "Pending Empty Pickup Report",
    ReportType.EXPENSE: "Expense Report",
    ReportType.FUEL: "Fuel Sheet Report",
    ReportType.STOCK_MOVEMENT: "Stock Movement Report",
    ReportType.PROFIT_LOSS: "Profit & Loss Statement",
    ReportType.TAX_GST: "GST Tax Report",
}

FINANCIAL_REPORTS = frozenset(
    {ReportType.EXPENSE, ReportType.FUEL, ReportType.PROFIT_LOSS}
)
