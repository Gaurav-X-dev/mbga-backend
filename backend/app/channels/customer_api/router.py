"""Customer API channel."""
from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.constants.router import router as constants_router
from app.modules.customers.document_router import build_document_router
from app.modules.customers.profile_router import router as customer_profile_router
from app.modules.customers.router import router as customer_registration_router
from app.modules.notifications.router import build_notification_router
from app.modules.orders.router import build_order_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_LOGIN"))
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_REGISTRATION", prefix="/registration"))
router.include_router(customer_registration_router)
# A customer needs no permission to reach their own documents; ownership is the rule, and
# the upload service enforces it.
router.include_router(build_document_router(LoginChannel.CUSTOMER))
router.include_router(customer_profile_router)
# A customer places and tracks their own orders. No permission is required - ownership
# is the rule, and the service scopes every query to their own customer id.
router.include_router(build_order_router(LoginChannel.CUSTOMER))
# The bell: the in-app list behind the push notifications (spec §15).
router.include_router(build_notification_router(LoginChannel.CUSTOMER))
# Public dropdown data. Mounted on both channels so each app calls its own base URL.
router.include_router(constants_router)
