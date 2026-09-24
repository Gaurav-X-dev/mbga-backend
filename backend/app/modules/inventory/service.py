"""Service layer for driver vehicle inventory (API Reference §10)."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.inventory.models import DriverInventory
from app.modules.inventory.schemas import DriverInventoryResponse


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_driver_inventory(self, driver_user_id: str) -> DriverInventoryResponse:
        inventory = await self.session.scalar(
            select(DriverInventory).where(DriverInventory.driver_user_id == driver_user_id)
        )
        if inventory is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "NOT_FOUND",
                    "message": "No vehicle inventory is assigned to this driver.",
                },
            )

        return DriverInventoryResponse(
            fullCylinderCount=inventory.full_cylinder_count,
            emptyCylinderCount=inventory.empty_cylinder_count,
            vehicleCapacity=inventory.vehicle_capacity,
            lastUpdatedAt=inventory.last_updated_at.isoformat(),
        )
