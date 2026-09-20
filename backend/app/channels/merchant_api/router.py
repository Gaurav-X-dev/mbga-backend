from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.review_router import router as customer_review_router
from app.modules.delivery_users.router import router as delivery_users_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.MERCHANT, "MERCHANT_LOGIN"))
router.include_router(delivery_users_router)
router.include_router(customer_review_router)
