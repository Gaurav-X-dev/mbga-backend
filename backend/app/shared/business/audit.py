"""Audit helper for business events.

Writes into the existing ``audit_logs`` table through the existing `AuditLogService`, so
business events sit beside the authentication events rather than in a parallel log.

Nothing sensitive is written: no tokens, OTPs, full mobile numbers, KYC identifiers or
document storage keys. `message` is a short operator-facing sentence, and identifiers are
opaque row ids that are meaningless without database access.
"""

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService, mask_mobile
from app.shared.business.actor import BusinessActor

# Values the existing auth events already use, so dashboards can filter on one vocabulary.
SUCCESS = "SUCCESS"
FAILURE = "FAILURE"

_MAX_MESSAGE = 255


class BusinessAuditor:
    """Records a business event on the caller's transaction; the caller commits."""

    def __init__(self, session, *, store_ip: bool = False, ip_address: str | None = None) -> None:
        self.service = AuditLogService(session)
        self.ip_address = ip_address if store_ip else None

    async def record(
        self,
        event_type: str,
        *,
        actor: BusinessActor,
        entity_type: str | None = None,
        entity_id: str | None = None,
        message: str | None = None,
        result: str = SUCCESS,
        reason_code: str | None = None,
        mobile_number: str | None = None,
    ) -> None:
        await self.service.write_event(
            AuditLogCreate(
                event_type=event_type,
                actor_user_id=actor.user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                message=(message or "")[:_MAX_MESSAGE] or None,
                login_channel=actor.login_channel.value,
                result=result,
                reason_code=reason_code,
                # Masked to the last four digits by the shared helper.
                masked_mobile=mask_mobile(mobile_number),
                ip_address=self.ip_address,
            )
        )
