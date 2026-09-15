from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel


class AuthenticationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_login_identity(self, *, mobile_number: str, country_code: str, login_channel: LoginChannel):
        # TODO: Query reviewed user/authentication tables once model design is approved.
        return None
