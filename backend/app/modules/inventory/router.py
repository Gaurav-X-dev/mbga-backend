"""FastAPI router for Inventory domain (API Reference §10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deliveries.dependencies import require_delivery_user
from app.modules.inventory.service import InventoryService
from app.shared.authorization.context import AuthContext
from app.shared.database.session import get_db_session
from app.shared.middleware.response_envelope import success_response

router = APIRouter(tags=["delivery-inventory"])


def get_inventory_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InventoryService:
    return InventoryService(session)


@router.get("/driver/inventory")
async def get_driver_inventory(
    auth: Annotated[AuthContext, Depends(require_delivery_user)],
    service: Annotated[InventoryService, Depends(get_inventory_service)],
):
    """GET /driver/inventory — §10: Driver vehicle stock counts."""
    inventory = await service.get_driver_inventory(driver_user_id=auth.user_id)
    return success_response(inventory.model_dump(by_alias=True))
