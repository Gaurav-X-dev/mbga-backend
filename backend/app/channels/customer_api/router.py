from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.router import router as customer_registration_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_LOGIN"))
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_REGISTRATION", prefix="/registration"))
router.include_router(customer_registration_router)
