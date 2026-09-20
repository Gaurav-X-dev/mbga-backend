"""Security-safe authentication audit events.

Stored: event type, user ID, app channel, result, reason code, masked mobile number, hashed device ID and
(if AUTH_AUDIT_STORE_IP is on) the client IP. Never stored: codes, tokens, secrets or full numbers.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_logs.schemas import AuditLogCreate
from app.modules.audit_logs.service import AuditLogService, hash_device, mask_mobile
from app.modules.authentication.constants import AuthEventType, LoginChannel


@dataclass(frozen=True)
class ClientInfo:
    ip_address: str | None = None
    user_agent: str | None = None


class AuthAuditor:
    def __init__(self, session: AsyncSession, *, store_ip: bool = True) -> None:
        self.service = AuditLogService(session)
        self.store_ip = store_ip

    async def record(
        self,
        event: AuthEventType,
        *,
        channel: LoginChannel | str | None,
        success: bool,
        user_id: str | None = None,
        mobile_number: str | None = None,
        device_id: str | None = None,
        client: ClientInfo | None = None,
        reason: str | None = None,
        entity_id: str | None = None,
    ) -> None:
        await self.service.write_event(
            AuditLogCreate(
                event_type=event.value,
                actor_user_id=user_id,
                entity_type="login_session" if entity_id else ("user" if user_id else None),
                entity_id=entity_id or user_id,
                message=None,
                login_channel=channel.value if isinstance(channel, LoginChannel) else channel,
                result="SUCCESS" if success else "FAILURE",
                reason_code=reason,
                masked_mobile=mask_mobile(mobile_number),
                device_hash=hash_device(device_id),
                ip_address=client.ip_address if client and self.store_ip else None,
            )
        )
