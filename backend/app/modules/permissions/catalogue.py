"""What each permission lets somebody do, and what it cannot work without.

Two problems this solves, both of them reported from the Permission Matrix screen.

**Nobody could tell the permissions apart.** `customers.review`, `customers.approve` and
`customers.verify` are three different jobs and three nearly identical labels. A sentence per
permission, written for the person ticking the box rather than for a developer, is the whole
fix.

**Granting one right was not enough to use it.** A salesperson given `users.create` still saw
no Users screen, because the list behind it needs `users.view`. The operator had to know that,
tick a second box, and be told off when they did not. So a permission now carries what it
depends on, and granting it grants those too - the box that was ticked stays the decision, and
the plumbing it needs stops being the operator's problem.

The dependency only ever adds *reading* rights. Granting "Create users" grants sight of the
Users list; it never grants blocking or deleting, and it never crosses into another module's
actions. A person ends up able to do exactly what was ticked, on screens they can now reach.
"""

from __future__ import annotations

#: One sentence per permission, in the operator's words. Keyed by code.
#:
#: These are read by whoever is deciding what a role may do, so they say what changes in the
#: world - "can collect money at the gate" - rather than naming the endpoint behind it.
DESCRIPTIONS: dict[str, str] = {
    # --- Authentication -------------------------------------------------------------------
    "authentication.view_sessions": "See who is signed in, on which app and from which device.",
    "authentication.revoke_sessions": "Sign somebody out of a device remotely, for example a lost phone.",
    "authentication.view_otp_logs": "See the OTPs the platform sent, and whether delivery succeeded.",
    # --- Orders ---------------------------------------------------------------------------
    "orders.view": "Open the Orders screen and read any order.",
    "orders.create": "Place an order on a customer's behalf.",
    "orders.update": "Change an order's cylinders or quantities before it is delivered.",
    "orders.assign": "Accept an order and assign the van, driver and delivery date.",
    "orders.cancel": "Cancel an order that has not been delivered.",
    # --- Driver app -----------------------------------------------------------------------
    "deliveries.view": "Driver app: see the trips assigned to you.",
    "deliveries.update_status": "Driver app: set off, reach the customer and confirm the handover.",
    # --- Office dispatch board --------------------------------------------------------------
    "delivery.view": "Open the Deliveries board and read any delivery slip.",
    "delivery.confirm": "Dispatch a slip and confirm what was handed over.",
    # --- Payments -------------------------------------------------------------------------
    "payments.view": "Open Payments and read invoices and collections.",
    "payments.collect": "Record money collected against an invoice.",
    "payments.reconcile": "Mark a UPI or NEFT payment as matched against the bank, or invalid.",
    # --- Inventory ------------------------------------------------------------------------
    "inventory.view": "See godown stock: filled, empty and damaged counts.",
    "inventory.adjust": "Receive stock and record corrections, with a reason.",
    # --- Tasks ----------------------------------------------------------------------------
    "tasks.view": "Open Tasks, and create, assign and update them.",
    # --- Reports --------------------------------------------------------------------------
    "reports.view": "Open Reports and read any of them on screen.",
    "reports.export": "Download a report as a file.",
    # --- Users ----------------------------------------------------------------------------
    "users.view": "Open the Users screen and read any user's profile.",
    "users.create": "Add a new user and set their mobile number and role.",
    "users.update": "Change a user's name, email or other details.",
    "users.activate": "Re-enable a user who was blocked or deactivated.",
    "users.block": "Block a user so they cannot sign in.",
    "users.manage": "Everything on the Users screen, including deleting a user.",
    "users.assign_roles": "Give a user a role.",
    "users.update_roles": "Change the roles a user already has.",
    "users.remove_roles": "Take a role away from a user.",
    "users.view_permissions": "See the full list of what a user can actually do.",
    "users.revoke_sessions": "Sign a user out of every device.",
    # --- Roles ----------------------------------------------------------------------------
    "roles.view": "Open the Roles screen and read any role.",
    "roles.create": "Create a new role.",
    "roles.update": "Rename a role or change its description.",
    "roles.delete": "Delete a role that nobody is using.",
    "roles.activate": "Turn a role on or off without deleting it.",
    "roles.assign_permissions": "Decide which permissions a role carries - the Permission Matrix.",
    "roles.assign_channels": "Decide which apps a role may sign in to: admin, merchant, delivery or customer.",
    "permissions.view": "See the catalogue of permissions the platform offers.",
    # --- Dashboard ------------------------------------------------------------------------
    "dashboard.view": "Open the dashboard and see its figures.",
    # --- Customers ------------------------------------------------------------------------
    "customers.view": "Open the Customers screen and read any customer.",
    "customers.create": "Register a new customer.",
    "customers.delete": "Permanently delete customers without business records. Assign only to trusted staff.",
    "customers.update": "Change a customer's details, addresses or delivery sites.",
    "customers.review": "Open a pending customer application and work through it.",
    "customers.approve": "Approve a customer application so they can order.",
    "customers.reject": "Reject a customer application, with a reason.",
    "customers.suspend": "Suspend an approved customer so they cannot order.",
    "customers.verify": "Mark a customer's KYC as verified.",
    "customer_documents.view": "Open the KYC documents a customer uploaded.",
    "customer_documents.review": "Work through a customer's documents one by one.",
    "customer_documents.approve": "Accept a KYC document.",
    "customer_documents.reject": "Reject a KYC document, with a reason.",
    # --- Merchants ------------------------------------------------------------------------
    "merchants.view": "Open Merchant Network and read any agency's record.",
    "merchants.create": "Add a new agency to the network.",
    "merchants.update": "Change an agency's details, address or invoice settings.",
    "merchants.activate": "Approve or re-enable an agency.",
    "merchants.block": "Block an agency so it cannot trade.",
    "merchants.manage": "Everything on the Merchant Network screen.",
    "merchant_users.view": "See the staff attached to an agency.",
    "merchant_users.create": "Add a staff member to an agency.",
    "merchant_users.update": "Change an agency staff member's details.",
    "merchant_users.assign_roles": "Decide what an agency's staff member may do.",
    # --- Drivers and the delivery team --------------------------------------------------
    "drivers.view": "See the drivers on the delivery team.",
    "drivers.manage": "Add, change and remove drivers.",
    "delivery_users.view": "Open Delivery Drivers and read any member's record.",
    "delivery_users.create": "Add a driver or helper to the delivery team.",
    "delivery_users.update": "Change a delivery team member's details.",
    "delivery_users.activate": "Re-enable a delivery team member.",
    "delivery_users.approve": "Approve a delivery team member so they can take trips.",
    "delivery_users.block": "Block a delivery team member from signing in.",
    "delivery_users.assign_roles": "Decide whether a member is a driver or a helper.",
    "trips.view": "See the rounds a van is running.",
    "trips.manage": "Plan and change rounds.",
    # --- Cylinders in and out ---------------------------------------------------------------
    "cylinder_exchange.view": "See the empties owed and returned by each customer.",
    "cylinder_exchange.update": "Record empties collected or adjusted.",
    "pending_pickups.view": "See the empties still waiting to be picked up.",
    "pending_pickups.update": "Settle a pending pickup.",
    # --- Money ------------------------------------------------------------------------------
    "pricing.view": "See this month's price card.",
    "pricing.manage": "Set and publish prices for a month.",
    "reconciliation.view": "See which collections have been matched against the bank.",
    "reconciliation.manage": "Match collections against the bank, or mark them invalid.",
    "ledgers.view": "Read a customer's account statement.",
    "expenses.view": "See the agency's recorded expenses.",
    "expenses.manage": "Record and change expenses.",
    "credit.view": "See a customer's credit limit and what they owe.",
    "credit.manage": "Set a customer's credit limit and terms.",
    "credit.override": "Let an order through even though it breaks the credit limit.",
    # --- Business catalogue -----------------------------------------------------------------
    "catalogue.view": "See the cylinder types, customer types and KYC document types in use.",
    "catalogue.manage": "Add and retire cylinder types, customer types and KYC document types, and set what each customer type may order.",
    # --- Platform ---------------------------------------------------------------------------
    "notifications.view": "Read the notifications the platform has sent.",
    "notifications.manage": "Change what the platform notifies people about.",
    "audit_logs.view": "Read the trail of who changed what, and when.",
    "platform_settings.view": "See the platform-wide settings.",
    "platform_settings.manage": "Change the platform-wide settings.",
}

#: Permissions whose module has no plain `<module>.view`, or which need something from another
#: module to be usable at all. Everything not listed here falls back to the general rule:
#: *an action on a module implies that module's own view.*
#:
#: These are reading rights only. Nothing here hands out a second action.
EXPLICIT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    # The sessions screen is the only place these act, and its read permission is not named
    # `authentication.view`.
    "authentication.revoke_sessions": ("authentication.view_sessions",),
    "authentication.view_otp_logs": ("authentication.view_sessions",),
    # The Permission Matrix lists the permission catalogue and the roles it applies to; without
    # both it opens empty, which is what made this screen confusing in the first place.
    "roles.assign_permissions": ("roles.view", "permissions.view"),
    "roles.assign_channels": ("roles.view",),
    # Giving somebody a role means picking from the list of roles.
    "users.assign_roles": ("users.view", "roles.view"),
    "users.update_roles": ("users.view", "roles.view"),
    "users.remove_roles": ("users.view", "roles.view"),
    "merchant_users.assign_roles": ("merchant_users.view", "roles.view"),
    "delivery_users.assign_roles": ("delivery_users.view", "roles.view"),
    # Staff of an agency are reached through the agency.
    "merchant_users.view": ("merchants.view",),
    # The office dispatch board is built on the orders it is dispatching.
    "delivery.confirm": ("delivery.view", "orders.view"),
    # Collecting money and reconciling it both start from an invoice.
    "payments.collect": ("payments.view",),
    "payments.reconcile": ("payments.view",),
    # A customer's documents hang off the customer.
    "customer_documents.view": ("customers.view",),
    "customer_documents.review": ("customer_documents.view", "customers.view"),
    "customer_documents.approve": ("customer_documents.view", "customers.view"),
    "customer_documents.reject": ("customer_documents.view", "customers.view"),
    # Credit is shown on the customer record.
    "credit.view": ("customers.view",),
    "credit.override": ("credit.view", "customers.view"),
    # A ledger is one customer's statement.
    "ledgers.view": ("customers.view",),
    # Assigning an order picks a van and a driver.
    "orders.assign": ("orders.view", "delivery_users.view"),
}

#: Actions that are not reads. Anything else ending in one of these is treated as a read and
#: implies nothing - there is no point making `orders.view` depend on itself.
_READ_ACTIONS = frozenset({"view", "view_sessions", "view_otp_logs", "view_permissions"})


def dependencies_for(code: str, known_codes: set[str]) -> tuple[str, ...]:
    """What `code` cannot be used without, out of the permissions that actually exist.

    The general rule is one line: an action on a module needs that module's view. Anything the
    rule cannot express - a differently named read, or a dependency on another module - is in
    `EXPLICIT_DEPENDENCIES`, and the two are combined rather than one overriding the other.

    `known_codes` is passed in rather than assumed, so a dependency on a permission that has
    been removed from the catalogue quietly drops out instead of being handed to a role that
    cannot use it.
    """
    required: list[str] = []

    module, _, action = code.partition(".")
    if action and action not in _READ_ACTIONS:
        module_view = f"{module}.view"
        if module_view != code and module_view in known_codes:
            required.append(module_view)

    for extra in EXPLICIT_DEPENDENCIES.get(code, ()):
        if extra != code and extra in known_codes and extra not in required:
            required.append(extra)

    return tuple(required)


def expand(codes: set[str], known_codes: set[str]) -> set[str]:
    """`codes` plus everything they depend on, following dependencies all the way down.

    Applied when a role's permissions are saved, so the stored set is always usable as it
    stands. A screen that asks "does this role have `users.view`?" gets the same answer as the
    operator who ticked "Create users" and expected the Users screen to appear.

    Iterates to a fixed point because a dependency can have dependencies of its own
    (`customer_documents.approve` needs `customer_documents.view`, which needs
    `customers.view`). The set only grows and the catalogue is finite, so this terminates.
    """
    resolved = set(codes)
    while True:
        added = set()
        for code in resolved:
            added.update(dependencies_for(code, known_codes))
        if added <= resolved:
            return resolved
        resolved |= added
