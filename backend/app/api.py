from fastapi import APIRouter

from app.channels.admin_api.router import router as admin_router
from app.channels.customer_api.router import router as customer_router
from app.channels.delivery_api.router import router as delivery_router
from app.channels.merchant_api.router import router as merchant_router

api_router = APIRouter()
api_router.include_router(customer_router, prefix="/customer")
api_router.include_router(delivery_router, prefix="/delivery")
api_router.include_router(merchant_router, prefix="/merchant")
api_router.include_router(admin_router, prefix="/admin")
