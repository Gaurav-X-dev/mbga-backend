"""Delivery V2 channel for split payment collection."""

from fastapi import APIRouter

from app.modules.driver.v2_router import router as deliveries_router

router = APIRouter()
router.include_router(deliveries_router)
