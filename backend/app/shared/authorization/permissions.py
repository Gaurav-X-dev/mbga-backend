from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.roles import UserRole

CHANNEL_ALLOWED_ROLES: dict[LoginChannel, set[UserRole]] = {
    LoginChannel.CUSTOMER: {UserRole.CUSTOMER},
    LoginChannel.DELIVERY: {UserRole.DELIVERY_PARTNER, UserRole.DRIVER, UserRole.HELPER},
    LoginChannel.MERCHANT: {
        UserRole.MERCHANT,
        UserRole.MANAGER,
        UserRole.SALESPERSON,
        UserRole.GODOWN_STOCK_MANAGER,
        UserRole.ACCOUNTANT,
    },
    LoginChannel.ADMIN: {UserRole.ADMIN},
}


def is_role_allowed_for_channel(role: UserRole, channel: LoginChannel) -> bool:
    return role in CHANNEL_ALLOWED_ROLES[channel]
