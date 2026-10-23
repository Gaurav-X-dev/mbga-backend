from fastapi import APIRouter

from app.channels.admin_api.router import router as admin_router
from app.channels.customer_api.router import router as customer_router
from app.channels.customer_api.v2_router import router as customer_v2_router
from app.channels.delivery_api.router import router as delivery_router
from app.channels.delivery_api.v2_router import router as delivery_v2_router
from app.channels.merchant_api.router import router as merchant_router
from app.channels.merchant_api.v2_router import router as merchant_v2_router

api_router = APIRouter()
api_v2_router = APIRouter()
api_v2_router.include_router(customer_v2_router, prefix='/customer')
api_v2_router.include_router(merchant_v2_router, prefix='/merchant')
api_v2_router.include_router(delivery_v2_router, prefix="/delivery")
api_router.include_router(customer_router, prefix="/customer")
api_router.include_router(delivery_router, prefix="/delivery")
api_router.include_router(merchant_router, prefix="/merchant")
api_router.include_router(admin_router, prefix="/admin")
