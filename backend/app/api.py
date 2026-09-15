from fastapi import APIRouter

from app.channels.admin_api.router import router as admin_router
from app.channels.customer_api.router import router as customer_router
from app.channels.delivery_api.router import router as delivery_router
from app.channels.merchant_api.router import router as merchant_router
from app.modules.authentication.router import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(customer_router, prefix="/customer", tags=["customer-api"])
api_router.include_router(delivery_router, prefix="/delivery", tags=["delivery-api"])
api_router.include_router(merchant_router, prefix="/merchant", tags=["merchant-api"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin-api"])
