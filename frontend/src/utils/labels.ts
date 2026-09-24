import { humanize } from "./format";

export type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "accent";

type StatusMeta = { label: string; tone: Tone };

const STATUS: Record<string, StatusMeta> = {
  ACTIVE: { label: "Active", tone: "success" },
  APPROVED: { label: "Approved", tone: "success" },
  PENDING: { label: "Pending", tone: "warning" },
  PENDING_APPROVAL: { label: "Pending approval", tone: "warning" },
  INACTIVE: { label: "Inactive", tone: "neutral" },
  BLOCKED: { label: "Blocked", tone: "danger" },
  REJECTED: { label: "Rejected", tone: "danger" },
  SUSPENDED: { label: "Suspended", tone: "danger" }
};

export function statusMeta(status: string | null | undefined): StatusMeta {
  if (!status) return { label: "Unknown", tone: "neutral" };
  return STATUS[status.toUpperCase()] ?? { label: humanize(status), tone: "neutral" };
}

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  admin_user: "Administrator",
  manager: "Merchant manager",
  salesperson: "Salesperson",
  godown_stock_manager: "Godown stock manager",
  accountant: "Accountant",
  driver: "Driver",
  helper: "Helper",
  customer: "Customer"
};

export function roleLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return ROLE_LABELS[code] ?? humanize(code);
}

export type ChannelCode = "ADMIN" | "MERCHANT" | "DELIVERY" | "CUSTOMER";

export const CHANNELS: Array<{ code: ChannelCode; label: string; description: string }> = [
  { code: "ADMIN", label: "Admin panel", description: "MBGA head-office web panel" },
  { code: "MERCHANT", label: "Merchant panel", description: "Merchant web panel and app" },
  { code: "DELIVERY", label: "Delivery app", description: "Drivers and helpers" },
  { code: "CUSTOMER", label: "Customer app", description: "Customer ordering app" }
];

export function channelLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return CHANNELS.find((channel) => channel.code === code.toUpperCase())?.label ?? humanize(code);
}

const STAFF_TYPE_LABELS: Record<string, string> = {
  PRIMARY_MANAGER: "Primary manager",
  MANAGER: "Manager"
};

export function staffTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STAFF_TYPE_LABELS[value.toUpperCase()] ?? humanize(value);
}

const DELIVERY_TYPE_LABELS: Record<string, string> = {
  DRIVER: "Driver",
  HELPER: "Helper"
};

export function deliveryTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return DELIVERY_TYPE_LABELS[value.toUpperCase()] ?? humanize(value);
}

/** Business-friendly names for permission modules, in display order. */
export const PERMISSION_MODULES: Record<string, { label: string; description: string }> = {
  dashboard: { label: "Dashboard", description: "Overview screens" },
  merchants: { label: "Merchant management", description: "Merchant businesses and their accounts" },
  merchant_users: { label: "Merchant staff", description: "People who work for a merchant" },
  customers: { label: "Customer management", description: "Customer applications and accounts" },
  customer_documents: { label: "Customer documents", description: "Documents submitted by customers" },
  users: { label: "User management", description: "Panel users and their access" },
  roles: { label: "Role management", description: "Roles and what they can do" },
  permissions: { label: "Permission catalogue", description: "The list of available permissions" },
  authentication: { label: "Sign-in and sessions", description: "Signed-in devices" },
  delivery_users: { label: "Delivery team", description: "Drivers and helpers" },
  drivers: { label: "Drivers", description: "Driver records" },
  trips: { label: "Trips", description: "Delivery trips" },
  deliveries: { label: "Deliveries", description: "Delivery progress" },
  orders: { label: "Orders", description: "Customer orders" },
  inventory: { label: "Inventory", description: "Cylinder stock" },
  cylinder_exchange: { label: "Cylinder exchange", description: "Empty and filled cylinder swaps" },
  pending_pickups: { label: "Pending pickups", description: "Cylinders awaiting collection" },
  pricing: { label: "Pricing", description: "Product prices" },
  payments: { label: "Payments", description: "Payment collection" },
  reconciliation: { label: "Reconciliation", description: "Payment matching" },
  ledgers: { label: "Ledgers", description: "Account ledgers" },
  expenses: { label: "Expenses", description: "Operating expenses" },
  reports: { label: "Reports", description: "Business reports" },
  notifications: { label: "Notifications", description: "Messages and alerts" },
  audit_logs: { label: "Audit and security", description: "Activity history" }
};

export function permissionModuleLabel(module: string): string {
  return PERMISSION_MODULES[module]?.label ?? humanize(module);
}

export function permissionModuleOrder(module: string): number {
  const index = Object.keys(PERMISSION_MODULES).indexOf(module);
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

const EVENT_LABELS: Record<string, string> = {
  "merchant.created": "Merchant added",
  "merchant.updated": "Merchant details updated",
  "merchant.active": "Merchant account activated",
  "merchant.blocked": "Merchant account blocked",
  "merchant_user.created": "Merchant staff member added",
  "merchant_user.updated": "Merchant staff member updated",
  "delivery_user.created": "Delivery team member added",
  "delivery_user.updated": "Delivery team member updated",
  "delivery_user.active": "Delivery team member activated",
  "delivery_user.blocked": "Delivery team member blocked",
  "user.created": "User added",
  "user.updated": "User details updated",
  "user.activated": "User account activated",
  "user.blocked": "User account blocked",
  "user.sessions_revoked": "User signed out from all devices",
  "user_role.assigned": "Role assigned to user",
  "user_role.updated": "User role updated",
  "user_role.removed": "Role removed from user",
  "role.created": "Role added",
  "role.updated": "Role updated",
  "role.deleted": "Role deleted",
  "role.activated": "Role activated",
  "role.deactivated": "Role deactivated",
  "role.permissions_replaced": "Role permissions changed",
  "role.permission_assigned": "Permission added to role",
  "role.permission_removed": "Permission removed from role",
  "role.channels_replaced": "Role panel access changed",
  "role.protected_rejected": "Protected role change blocked"
};

export const AUDIT_EVENT_OPTIONS = Object.entries(EVENT_LABELS).map(([value, label]) => ({ value, label }));

export function auditEventLabel(eventType: string): string {
  return EVENT_LABELS[eventType] ?? humanize(eventType);
}

const ENTITY_LABELS: Record<string, string> = {
  merchant: "Merchants",
  merchant_user: "Merchant staff",
  delivery_profile: "Delivery team",
  user: "Users",
  role: "Roles"
};

export const AUDIT_ENTITY_OPTIONS = Object.entries(ENTITY_LABELS).map(([value, label]) => ({ value, label }));

export function auditEntityLabel(entityType: string | null | undefined): string {
  if (!entityType) return "—";
  return ENTITY_LABELS[entityType] ?? humanize(entityType);
}

/** Backend descriptions are often just "System permission: <name>"; only show ones that add information. */
export function permissionDescription(item: { name: string; description: string | null }): string | undefined {
  const description = item.description?.trim();
  if (!description) return undefined;
  const plain = description.replace(/^system permission:\s*/i, "");
  return plain.toLowerCase() === item.name.trim().toLowerCase() ? undefined : description;
}

/** Hides seeded descriptions such as "System role: Manager" that only repeat the name. */
export function roleDescription(role: { name: string; description: string | null }): string | undefined {
  const description = role.description?.trim();
  if (!description) return undefined;
  const plain = description.replace(/^system role:\s*/i, "");
  return plain.toLowerCase() === role.name.trim().toLowerCase() ? undefined : description;
}
