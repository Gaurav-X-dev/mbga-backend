import type { AuditLogListParams } from "./audit-logs.api";
import type { KycListParams } from "./customer-kyc.api";
import type { DashboardAnalyticsParams } from "./dashboard.api";
import type { DeliveryMemberListParams } from "./delivery-team.api";
import type { LoginSessionListParams } from "./sessions.api";
import type { MerchantListParams } from "./merchants.api";
import type { DeliveryListParams } from "./deliveries.api";
import type { AdminDeliveryUserListParams } from "./delivery-users.api";
import type { CreditReportParams } from "./credit.api";
import type { CustomerListParams } from "./customers.api";
import type { ExpenseListParams } from "./expenses.api";
import type { TaskListParams } from "./tasks.api";
import type { MovementListParams } from "./inventory.api";
import type { OrderListParams } from "./orders.api";
import type { InvoiceListParams, PaymentListParams } from "./payments.api";
import type { ReportParams } from "./reports.api";
import type { RoleListParams } from "./roles.api";
import type { UserListParams } from "./users.api";
import type { OtpLogParams } from "./otp-logs.api";
import type { PricingChangeLogParams } from "./pricing.api";
import type { VehicleListParams } from "./vehicles.api";

/**
 * Query keys grouped by feature. Every key starts with the channel so that an Admin
 * cache entry can never be served to a Merchant session (the cache is also cleared on sign-out).
 */
export const queryKeys = {
  me: (channel: string) => ["auth", channel, "me"] as const,

  adminDashboard: {
    all: ["admin", "dashboard"] as const,
    summary: () => ["admin", "dashboard", "summary"] as const,
    analytics: (params: DashboardAnalyticsParams) => ["admin", "dashboard", "analytics", params] as const
  },

  loginSessions: {
    all: ["admin", "login-sessions"] as const,
    lists: () => ["admin", "login-sessions", "list"] as const,
    list: (params: LoginSessionListParams) => ["admin", "login-sessions", "list", params] as const,
    stats: () => ["admin", "login-sessions", "stats"] as const
  },

  customerKyc: {
    all: ["admin", "customer-kyc"] as const,
    lists: () => ["admin", "customer-kyc", "list"] as const,
    list: (params: KycListParams) => ["admin", "customer-kyc", "list", params] as const,
    stats: () => ["admin", "customer-kyc", "stats"] as const,
    detail: (applicationId: string) => ["admin", "customer-kyc", "detail", applicationId] as const
  },

  merchants: {
    all: ["admin", "merchants"] as const,
    lists: () => ["admin", "merchants", "list"] as const,
    list: (params: MerchantListParams) => ["admin", "merchants", "list", params] as const,
    detail: (merchantId: string) => ["admin", "merchants", "detail", merchantId] as const,
    users: (merchantId: string) => ["admin", "merchants", "detail", merchantId, "users"] as const
  },

  users: {
    all: ["admin", "users"] as const,
    lists: () => ["admin", "users", "list"] as const,
    list: (params: UserListParams) => ["admin", "users", "list", params] as const,
    detail: (userId: string) => ["admin", "users", "detail", userId] as const,
    roles: (userId: string) => ["admin", "users", "detail", userId, "roles"] as const,
    permissions: (userId: string, channel: string) =>
      ["admin", "users", "detail", userId, "permissions", channel] as const,
    channels: (userId: string) => ["admin", "users", "detail", userId, "channels"] as const
  },

  catalogue: {
    all: ["admin", "catalogue"] as const,
    cylinderTypes: (params: unknown) => ["admin", "catalogue", "cylinder-types", params] as const,
    customerTypes: (params: unknown) => ["admin", "catalogue", "customer-types", params] as const,
    kycDocumentTypes: (params: unknown) => ["admin", "catalogue", "kyc-document-types", params] as const,
    eligibility: (code: string) => ["admin", "catalogue", "eligibility", code] as const,
    kycRules: (code: string) => ["admin", "catalogue", "kyc-rules", code] as const
  },
  roles: {
    all: ["admin", "roles"] as const,
    lists: () => ["admin", "roles", "list"] as const,
    list: (params: RoleListParams) => ["admin", "roles", "list", params] as const,
    detail: (roleId: string) => ["admin", "roles", "detail", roleId] as const,
    permissions: (roleId: string) => ["admin", "roles", "detail", roleId, "permissions"] as const,
    channels: (roleId: string) => ["admin", "roles", "detail", roleId, "channels"] as const,
    users: (roleId: string) => ["admin", "roles", "detail", roleId, "users"] as const
  },

  permissions: {
    grouped: () => ["admin", "permissions", "grouped"] as const
  },

  auditLogs: {
    all: ["admin", "audit-logs"] as const,
    list: (params: AuditLogListParams) => ["admin", "audit-logs", "list", params] as const,
    detail: (auditLogId: string) => ["admin", "audit-logs", "detail", auditLogId] as const
  },

  credit: {
    all: ["admin", "credit"] as const,
    settings: () => ["admin", "credit", "settings"] as const,
    report: (params: CreditReportParams) => ["admin", "credit", "report", params] as const,
    history: (customerId: string) => ["admin", "credit", "history", customerId] as const
  },

  customers: {
    all: ["admin", "customers"] as const,
    list: (params: CustomerListParams) => ["admin", "customers", "list", params] as const,
    detail: (merchantId: string, customerId: string) => ["admin", "customers", "detail", merchantId, customerId] as const,
    eligibility: (merchantId: string, customerId: string) => ["admin", "customers", "detail", merchantId, customerId, "eligibility"] as const,
    pricing: (merchantId: string, customerId: string) => ["admin", "customers", "detail", merchantId, customerId, "pricing"] as const,
    payments: (merchantId: string, customerId: string) => ["admin", "customers", "detail", merchantId, customerId, "payments"] as const
  },

  reports: {
    all: ["admin", "reports"] as const,
    detail: (params: ReportParams) => ["admin", "reports", params] as const
  },

  payments: {
    all: ["admin", "payments"] as const,
    list: (params: PaymentListParams) => ["admin", "payments", "list", params] as const,
    detail: (merchantId: string, paymentId: string) => ["admin", "payments", "detail", merchantId, paymentId] as const,
    invoices: (params: InvoiceListParams) => ["admin", "payments", "invoices", params] as const,
    invoice: (merchantId: string, invoiceId: string) => ["admin", "payments", "invoice", merchantId, invoiceId] as const,
    proof: (merchantId: string, paymentId: string) => ["admin", "payments", "proof", merchantId, paymentId] as const,
    einvoice: (merchantId: string, invoiceId: string) => ["admin", "payments", "einvoice", merchantId, invoiceId] as const
  },

  pricing: {
    all: ["admin", "pricing"] as const,
    months: (merchantId: string) => ["admin", "pricing", "months", merchantId] as const,
    logs: (params: PricingChangeLogParams) => ["admin", "pricing", "logs", params] as const
  },
  vehicles: {
    all: ["admin", "vehicles"] as const,
    list: (params: VehicleListParams) => ["admin", "vehicles", "list", params] as const,
    available: (merchantId: string) => ["admin", "vehicles", "available", merchantId] as const,
    pincodes: (merchantId: string, vehicleId: string) => ["admin", "vehicles", "pincodes", merchantId, vehicleId] as const,
    forOrder: (merchantId: string, orderId: string) => ["admin", "vehicles", "for-order", merchantId, orderId] as const,
    forDelivery: (merchantId: string, deliveryId: string) => ["admin", "vehicles", "for-delivery", merchantId, deliveryId] as const
  },
  otpLogs: {
    all: ["admin", "otp-logs"] as const,
    list: (params: OtpLogParams) => ["admin", "otp-logs", "list", params] as const
  },
  locations: {
    pincode: (pincode: string, merchantId?: string) => ["admin", "locations", "pincode", pincode, merchantId ?? ""] as const
  },

  deliveryUsers: {
    all: ["admin", "delivery-users"] as const,
    list: (params: AdminDeliveryUserListParams) => ["admin", "delivery-users", "list", params] as const,
    available: (merchantId: string, type: string) => ["admin", "delivery-users", "available", merchantId, type] as const,
    detail: (merchantId: string, id: string) => ["admin", "delivery-users", "detail", merchantId, id] as const
  },

  deliveries: {
    all: ["admin", "deliveries"] as const,
    list: (params: DeliveryListParams) => ["admin", "deliveries", "list", params] as const,
    detail: (merchantId: string, deliveryId: string) => ["admin", "deliveries", "detail", merchantId, deliveryId] as const
  },

  tasks: {
    all: ["admin", "tasks"] as const,
    list: (params: TaskListParams) => ["admin", "tasks", "list", params] as const,
    detail: (merchantId: string, taskId: string) => ["admin", "tasks", "detail", merchantId, taskId] as const,
    messages: (merchantId: string, taskId: string) => ["admin", "tasks", "detail", merchantId, taskId, "messages"] as const,
    activity: (merchantId: string, taskId: string) => ["admin", "tasks", "detail", merchantId, taskId, "activity"] as const,
    team: (merchantId: string) => ["admin", "tasks", "team", merchantId] as const
  },

  expenses: {
    all: ["admin", "expenses"] as const,
    list: (params: ExpenseListParams) => ["admin", "expenses", "list", params] as const,
    periods: (merchantId: string) => ["admin", "expenses", "periods", merchantId] as const,
    breakdown: (merchantId: string, period: string) => ["admin", "expenses", "breakdown", merchantId, period] as const,
    categories: (merchantId: string, includeInactive: boolean) =>
      ["admin", "expenses", "categories", merchantId, includeInactive] as const
  },

  inventory: {
    all: ["admin", "inventory"] as const,
    snapshot: (merchantId: string) => ["admin", "inventory", "snapshot", merchantId] as const,
    movements: (params: MovementListParams) => ["admin", "inventory", "movements", params] as const
  },

  orders: {
    all: ["admin", "orders"] as const,
    list: (params: OrderListParams) => ["admin", "orders", "list", params] as const,
    detail: (merchantId: string, orderId: string) => ["admin", "orders", "detail", merchantId, orderId] as const,
    statuses: (merchantId: string) => ["admin", "orders", "statuses", merchantId] as const,
    cutoff: (merchantId: string) => ["admin", "orders", "cutoff", merchantId] as const
  },

  deliveryTeam: {
    all: ["merchant", "delivery-team"] as const,
    lists: () => ["merchant", "delivery-team", "list"] as const,
    list: (params: DeliveryMemberListParams) => ["merchant", "delivery-team", "list", params] as const,
    detail: (memberId: string) => ["merchant", "delivery-team", "detail", memberId] as const
  }
};
