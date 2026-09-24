from fastapi import APIRouter

from app.channels.delivery_api.auth_router import router as delivery_auth_router
from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.deliveries.router import router as deliveries_router
from app.modules.driver_profile.router import router as driver_profile_router
from app.modules.inventory.router import router as inventory_router
from app.modules.notifications.router import router as notifications_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router

router = APIRouter()

# Authentication (API_REFERENCE §5 + legacy channel auth routes)
router.include_router(delivery_auth_router)
router.include_router(build_channel_auth_router(LoginChannel.DELIVERY, "DELIVERY_LOGIN"))

# Deliveries (§6.1, §6.2, §7.1, §7.2, §7.3)
router.include_router(deliveries_router)

# Orders (§6.2, §6.3, §6.4)
router.include_router(orders_router)

# Driver Profile & Status (§8.1, §8.2, §8.3)
router.include_router(driver_profile_router)

# Notifications (§9.1, §9.2)
router.include_router(notifications_router)

# Inventory / Stock (§10)
router.include_router(inventory_router)

# Payments (§11.1, §11.2, §11.3)
router.include_router(payments_router)


@router.get("/login-channel")
async def login_channel() -> dict[str, LoginChannel]:
    return {"login_channel": LoginChannel.DELIVERY}
