from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.permissions import is_role_allowed_for_channel
from app.shared.authorization.roles import UserRole


def ensure_channel_role_allowed(role: UserRole, channel: LoginChannel) -> None:
    if not is_role_allowed_for_channel(role, channel):
        from app.modules.authentication.exceptions import LoginNotAllowedError

        raise LoginNotAllowedError()
