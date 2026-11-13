from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.modules.audit_logs.models import AuditLog
from app.modules.finance.models import FinanceSettings
from app.modules.finance.schemas import FinancePolicy
from app.shared.exceptions.api_error import ApiError


def audit(session, actor_id, entity_id, message):
    session.add(
        AuditLog(
            id=str(uuid4()),
            event_type="FINANCE_UPDATED",
            actor_user_id=actor_id,
            entity_type="finance",
            entity_id=entity_id,
            message=message[:255],
            created_at=datetime.now(UTC),
        )
    )


async def policy(session, merchant_id):
    rows = (
        await session.scalars(
            select(FinanceSettings).where(FinanceSettings.scope.in_(["platform", merchant_id]))
        )
    ).all()
    configs = {row.scope: FinancePolicy.model_validate_json(row.config) for row in rows}
    if "platform" not in configs:
        raise ApiError(
            "FINANCE_MIGRATION_REQUIRED",
            503,
            "Apply the finance migration before using this feature.",
        )
    return configs.get(merchant_id, configs["platform"])
