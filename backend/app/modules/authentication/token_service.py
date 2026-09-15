from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.config.app import Settings
from app.modules.authentication.schemas import TokenPair


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def create_access_token(self, *, subject: str, role: str, extra_claims: dict[str, Any] | None = None) -> str:
        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.access_token_expires_minutes)
        payload: dict[str, Any] = {"sub": subject, "role": role, "type": "access", "exp": expires_at}
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)

    def create_refresh_token(self, *, subject: str, session_id: str) -> str:
        expires_at = datetime.now(UTC) + timedelta(days=self.settings.refresh_token_expires_days)
        payload = {"sub": subject, "sid": session_id, "type": "refresh", "exp": expires_at}
        return jwt.encode(payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)

    def create_token_pair(self, *, subject: str, role: str, session_id: str) -> TokenPair:
        return TokenPair(
            access_token=self.create_access_token(subject=subject, role=role),
            refresh_token=self.create_refresh_token(subject=subject, session_id=session_id),
            expires_in=self.settings.access_token_expires_minutes * 60,
        )
