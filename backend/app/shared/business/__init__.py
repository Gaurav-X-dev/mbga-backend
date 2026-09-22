"""Business-layer foundations shared by the Customer and Merchant APIs.

Adapters and policies that sit *on top of* the frozen authentication layer: they consume
`AuthContext` and never modify how a session is established.
"""

from app.shared.business.actor import BusinessActor, BusinessActorResolver
from app.shared.business.audit import FAILURE, SUCCESS, BusinessAuditor
from app.shared.business.filters import DateRange, month_range, validate_date_range, validate_month
from app.shared.business.pagination import Page, PaginatedResponse, page_params, paginate
from app.shared.business.policies import (
    ensure_customer_owns,
    ensure_merchant_owns,
    ensure_own_customer_id,
    ensure_visible,
    require_channel,
    scope_to_customer,
    scope_to_merchant,
)
from app.shared.business.transitions import StatusMachine

__all__ = [
    "FAILURE",
    "SUCCESS",
    "BusinessActor",
    "BusinessActorResolver",
    "BusinessAuditor",
    "DateRange",
    "Page",
    "PaginatedResponse",
    "StatusMachine",
    "ensure_customer_owns",
    "ensure_merchant_owns",
    "ensure_own_customer_id",
    "ensure_visible",
    "month_range",
    "page_params",
    "paginate",
    "require_channel",
    "scope_to_customer",
    "scope_to_merchant",
    "validate_date_range",
    "validate_month",
]
