"""Everything the delivery app can reach.

A driver is not merchant staff. They hold no role in the permission matrix, and they are
authorised by being the person a slip is addressed to - which every query enforces in its
`WHERE`, not in a guard. So there are no permission dependencies on this channel, and a token
minted on any other channel is refused.

Orders are deliberately **not** mounted here. A driver needs the drop, not the sale: the
delivery routes already carry the customer, the address, the cylinders and the counts, while an
order carries prices, GST and the customer's own history. Mounting `/orders` would hand every
driver the merchant's commercial record for the sake of fields they already have.

Payments (API_REFERENCE §11) are absent for the same kind of reason - there is no payment module
on the platform, and the app's own reference marks them "confirm scope before building".
"""

from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.driver.router import deliveries_router, driver_router
from app.modules.notifications.router import build_notification_router

router = APIRouter()

router.include_router(build_channel_auth_router(LoginChannel.DELIVERY, "DELIVERY_LOGIN"))

# The driver's bell. A driver is not staff, so they read only what is addressed to them
# personally - `recipient_kind = "user"` - never the merchant's shared bucket. "New order
# received" is for the office; "your delivery is ready" is for them.
router.include_router(build_notification_router(LoginChannel.DELIVERY))

# The work: today's queue, the trip, the handover (API_REFERENCE §6, §7).
router.include_router(deliveries_router)

# The driver's own record and what is on their van (§8, §10).
router.include_router(driver_router)
