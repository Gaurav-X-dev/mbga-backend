"""Merchant V2 channel for multi-image KYC review."""

from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.merchant_v2_customer_router import router as customer_router
from app.modules.customers.merchant_v2_document_router import router as document_router
from app.modules.customers.merchant_v2_router import router as kyc_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.MERCHANT, "MERCHANT_LOGIN"))
router.include_router(customer_router)
router.include_router(kyc_router)
router.include_router(document_router)
