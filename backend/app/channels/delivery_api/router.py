from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.notifications.router import build_notification_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.DELIVERY, "DELIVERY_LOGIN"))
# The driver's bell. A driver is not staff, so they read only what is addressed to them
# personally - `recipient_kind = "user"` - never the merchant's shared bucket. "New order
# received" is for the office; "your delivery is ready" is for them.
router.include_router(build_notification_router(LoginChannel.DELIVERY))
