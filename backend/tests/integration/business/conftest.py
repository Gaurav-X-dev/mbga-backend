"""Fixtures for Phase B business-infrastructure tests.

Re-exports the authentication suite's database and environment fixtures rather than
rebuilding them, so there is one migration/seed path for the whole integration suite. The
authentication conftest is not edited — these tests only consume it.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.shared.authorization.context import AuthContext
from app.shared.business.actor import BusinessActor, BusinessActorResolver

# Imported for pytest to collect them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    database_url,
    env,
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


def auth_context(user_id: str, channel: LoginChannel, session_id: str = "test-session") -> AuthContext:
    """The validated context the auth layer hands to business code."""
    return AuthContext(user_id=user_id, login_channel=channel, session_id=session_id)


async def resolve_actor(db: AsyncSession, user_id: str, channel: LoginChannel) -> BusinessActor:
    return await BusinessActorResolver(db).resolve(auth_context(user_id, channel))
