"""Customer v2 channel. V1 remains mounted independently and unchanged."""

from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.v2_document_router import router as document_router
from app.modules.customers.v2_router import router as registration_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_LOGIN"))
router.include_router(build_channel_auth_router(LoginChannel.CUSTOMER, "CUSTOMER_REGISTRATION", prefix="/registration"))
router.include_router(registration_router)
router.include_router(document_router)
