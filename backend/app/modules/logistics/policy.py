from sqlalchemy import select

from app.modules.logistics.models import LogisticsSettings
from app.modules.logistics.schemas import LogisticsPolicy
from app.shared.exceptions.api_error import ApiError


async def policy(session, merchant_id):
    rows = (
        await session.scalars(
            select(LogisticsSettings).where(LogisticsSettings.scope.in_(["platform", merchant_id]))
        )
    ).all()
    values = {r.scope: LogisticsPolicy.model_validate_json(r.config) for r in rows}
    if "platform" not in values:
        raise ApiError(
            "LOGISTICS_MIGRATION_REQUIRED",
            503,
            "Apply the logistics migration before using trips or priorities.",
        )
    return values.get(merchant_id, values["platform"])


async def priority_code(session, merchant_id, code=None):
    config = await policy(session, merchant_id)
    wanted = code or config.defaultPriority
    if wanted not in {p.code for p in config.priorities}:
        raise ApiError(
            "PRIORITY_INVALID", 422, "Select a priority from the merchant's current options."
        )
    return wanted
