from dataclasses import dataclass

from app.modules.authentication.constants import LoginChannel


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    login_channel: LoginChannel
    session_id: str | None = None
    token_type: str = "access"
