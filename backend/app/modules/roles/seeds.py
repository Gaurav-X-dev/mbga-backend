from dataclasses import dataclass

from app.modules.authentication.constants import LoginChannel


@dataclass(frozen=True)
class SeedRole:
    code: str
    name: str
    channels: tuple[LoginChannel, ...]


@dataclass(frozen=True)
class SeedPermission:
    code: str
    name: str
    module: str
    action: str


SEED_ROLES: tuple[SeedRole, ...] = (
    SeedRole("customer", "Customer", (LoginChannel.CUSTOMER,)),
    SeedRole("driver", "Driver", (LoginChannel.DELIVERY,)),
    SeedRole("helper", "Helper", (LoginChannel.DELIVERY,)),
    SeedRole("manager", "Manager", (LoginChannel.MERCHANT,)),
    SeedRole("salesperson", "Salesperson", (LoginChannel.MERCHANT,)),
    SeedRole("godown_stock_manager", "Godown Stock Manager", (LoginChannel.MERCHANT,)),
    SeedRole("accountant", "Accountant", (LoginChannel.MERCHANT,)),
    SeedRole("super_admin", "Super Admin", (LoginChannel.ADMIN,)),
)

SEED_PERMISSIONS: tuple[SeedPermission, ...] = (
    SeedPermission("authentication.view_sessions", "View auth sessions", "authentication", "view_sessions"),
    SeedPermission("authentication.revoke_sessions", "Revoke auth sessions", "authentication", "revoke_sessions"),
    SeedPermission("orders.view", "View orders", "orders", "view"),
    SeedPermission("orders.create", "Create orders", "orders", "create"),
    SeedPermission("orders.update", "Update orders", "orders", "update"),
    SeedPermission("orders.assign", "Assign orders", "orders", "assign"),
    SeedPermission("orders.cancel", "Cancel orders", "orders", "cancel"),
    SeedPermission("deliveries.view", "View deliveries", "deliveries", "view"),
    SeedPermission("deliveries.update_status", "Update delivery status", "deliveries", "update_status"),
    SeedPermission("payments.collect", "Collect payments", "payments", "collect"),
    SeedPermission("payments.reconcile", "Reconcile payments", "payments", "reconcile"),
    SeedPermission("inventory.view", "View inventory", "inventory", "view"),
    SeedPermission("inventory.adjust", "Adjust inventory", "inventory", "adjust"),
    SeedPermission("reports.view", "View reports", "reports", "view"),
    SeedPermission("reports.export", "Export reports", "reports", "export"),
    SeedPermission("users.view", "View users", "users", "view"),
    SeedPermission("users.create", "Create users", "users", "create"),
    SeedPermission("users.update", "Update users", "users", "update"),
    SeedPermission("users.activate", "Activate users", "users", "activate"),
    SeedPermission("users.block", "Block users", "users", "block"),
    SeedPermission("users.manage", "Manage users", "users", "manage"),
    SeedPermission("users.assign_roles", "Assign user roles", "users", "assign_roles"),
    SeedPermission("users.update_roles", "Update user role assignments", "users", "update_roles"),
    SeedPermission("users.remove_roles", "Remove user role assignments", "users", "remove_roles"),
    SeedPermission("users.view_permissions", "View user effective permissions", "users", "view_permissions"),
    SeedPermission("users.revoke_sessions", "Revoke user sessions", "users", "revoke_sessions"),
    SeedPermission("roles.view", "View roles", "roles", "view"),
    SeedPermission("roles.create", "Create roles", "roles", "create"),
    SeedPermission("roles.update", "Update roles", "roles", "update"),
    SeedPermission("roles.delete", "Delete roles", "roles", "delete"),
    SeedPermission("roles.activate", "Activate roles", "roles", "activate"),
    SeedPermission("roles.assign_permissions", "Assign role permissions", "roles", "assign_permissions"),
    SeedPermission("roles.assign_channels", "Assign role login channels", "roles", "assign_channels"),
    SeedPermission("permissions.view", "View permissions", "permissions", "view"),
    SeedPermission("dashboard.view", "View admin dashboard", "dashboard", "view"),
    SeedPermission("customers.view", "View customers", "customers", "view"),
    SeedPermission("customers.create", "Create customers", "customers", "create"),
    SeedPermission("customers.update", "Update customers", "customers", "update"),
    SeedPermission("customers.review", "Review customer applications", "customers", "review"),
    SeedPermission("customers.approve", "Approve customers", "customers", "approve"),
    SeedPermission("customers.reject", "Reject customers", "customers", "reject"),
    SeedPermission("customers.suspend", "Suspend customers", "customers", "suspend"),
    SeedPermission("customers.verify", "Verify customer KYC", "customers", "verify"),
    SeedPermission("customer_documents.view", "View customer documents", "customer_documents", "view"),
    SeedPermission("customer_documents.review", "Review customer documents", "customer_documents", "review"),
    SeedPermission("customer_documents.approve", "Approve customer documents", "customer_documents", "approve"),
    SeedPermission("customer_documents.reject", "Reject customer documents", "customer_documents", "reject"),
    SeedPermission("merchants.view", "View merchant records", "merchants", "view"),
    SeedPermission("merchants.create", "Create merchant records", "merchants", "create"),
    SeedPermission("merchants.update", "Update merchant records", "merchants", "update"),
    SeedPermission("merchants.activate", "Activate merchant records", "merchants", "activate"),
    SeedPermission("merchants.block", "Block merchant records", "merchants", "block"),
    SeedPermission("merchants.manage", "Manage merchant records", "merchants", "manage"),
    SeedPermission("drivers.view", "View drivers", "drivers", "view"),
    SeedPermission("drivers.manage", "Manage drivers", "drivers", "manage"),
    SeedPermission("delivery_users.create", "Create delivery users", "delivery_users", "create"),
    SeedPermission("delivery_users.view", "View delivery users", "delivery_users", "view"),
    SeedPermission("delivery_users.update", "Update delivery users", "delivery_users", "update"),
    SeedPermission("delivery_users.approve", "Approve delivery users", "delivery_users", "approve"),
    SeedPermission("delivery_users.block", "Block delivery users", "delivery_users", "block"),
    SeedPermission("trips.view", "View trips", "trips", "view"),
    SeedPermission("trips.manage", "Manage trips", "trips", "manage"),
    SeedPermission("cylinder_exchange.view", "View cylinder exchange", "cylinder_exchange", "view"),
    SeedPermission("cylinder_exchange.update", "Update cylinder exchange", "cylinder_exchange", "update"),
    SeedPermission("pending_pickups.view", "View pending pickups", "pending_pickups", "view"),
    SeedPermission("pending_pickups.update", "Update pending pickups", "pending_pickups", "update"),
    SeedPermission("pricing.view", "View pricing", "pricing", "view"),
    SeedPermission("pricing.manage", "Manage pricing", "pricing", "manage"),
    SeedPermission("payments.view", "View payments", "payments", "view"),
    SeedPermission("reconciliation.view", "View reconciliation", "reconciliation", "view"),
    SeedPermission("reconciliation.manage", "Manage reconciliation", "reconciliation", "manage"),
    SeedPermission("ledgers.view", "View ledgers", "ledgers", "view"),
    SeedPermission("expenses.view", "View expenses", "expenses", "view"),
    SeedPermission("expenses.manage", "Manage expenses", "expenses", "manage"),
    SeedPermission("notifications.view", "View notifications", "notifications", "view"),
    SeedPermission("notifications.manage", "Manage notifications", "notifications", "manage"),
    SeedPermission("audit_logs.view", "View audit logs", "audit_logs", "view"),
)


UNRESOLVED_ROLE_PERMISSION_MAPPING = {
    "customer": "Own order/payment/profile permissions need scoped policies before broad grants.",
    "manager": "Manager has broad business access in documents, but exact admin-channel boundary needs confirmation.",
    "super_admin": "Bootstrap is environment-controlled; never auto-assign from public registration.",
}
