"""Reading and changing the platform's operating values.

The read is deliberately a plain primary-key lookup with no cache. One indexed row per order
placement is nothing beside the work of placing an order, and a cache would mean an operator
changing the cut-off at 3pm watches orders keep using the old one until something expires - or,
worse, until only some of the API workers notice.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_settings.models import (
    DEFAULT_ORDER_CUTOFF_HOUR,
    SINGLETON_ID,
    PlatformSettings,
)
from app.shared.business.actor import BusinessActor


async def load(session: AsyncSession) -> PlatformSettings:
    """The settings row, created on first use rather than assumed to exist.

    A deployment whose migration seeded the row gets it. One restored from a dump taken before
    this existed gets a row with the shipped defaults instead of a 500 on every order.
    """
    settings = await session.get(PlatformSettings, SINGLETON_ID)
    if settings is None:
        settings = PlatformSettings(
            id=SINGLETON_ID,
            order_cutoff_hour=DEFAULT_ORDER_CUTOFF_HOUR,
            updated_at=datetime.now(UTC),
        )
        session.add(settings)
        await session.flush()
    return settings


async def order_cutoff_hour(session: AsyncSession) -> int:
    """The configured cut-off hour, IST."""
    return (await load(session)).order_cutoff_hour


async def update(
    session: AsyncSession, actor: BusinessActor, *, order_cutoff_hour: int | None = None
) -> PlatformSettings:
    """Apply the changes an admin made, naming who made them.

    Unset fields are left alone, so a panel that only edits the cut-off cannot blank a setting it
    does not know about yet.
    """
    settings = await load(session)
    if order_cutoff_hour is not None:
        settings.order_cutoff_hour = order_cutoff_hour
    settings.updated_by_user_id = actor.user_id
    settings.updated_by_name = actor.display_name
    settings.updated_at = datetime.now(UTC)
    await session.commit()
    return settings
