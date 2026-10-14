"""Reading the OTP itself off the admin log screen.

Asked for when the SMS credit ran out: with no message arriving nobody could sign in, and the
office needed the code from somewhere. A challenge only ever held a one-way hash, so there was
no code to print - `OTP_LOG_PLAINTEXT_ENABLED` is what puts one there.

These tests pin both halves of that switch, because the dangerous half is the one that is easy
to leave on by accident:

* on  - the code comes back, and the audit row says so in its own event type
* off - every row's `otp` is null and nothing is stored, which is the default

The hash is written either way. Verification never reads the plaintext, so turning the switch
off leaves sign-in working exactly as it did.
"""

import pytest

from app.modules.authentication.otp_models import OtpChallenge
from tests.integration.authentication.conftest import (  # noqa: F401 - fixtures
    AuthEnv,
    _prepared_database,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
OTP_LOGS = "/api/v1/admin/auth/otp-logs"


@pytest.fixture
def settings_overrides() -> dict:
    """Readable codes on, as a deployment with no SMS credit would set it."""
    return {"otp_log_plaintext_enabled": True}


async def an_admin(env):
    user = await env.create_user(roles=("super_admin",))
    login = await env.sign_in(ADMIN_AUTH, user.mobile_number)
    return login["token"]["access_token"]


async def a_challenge(env) -> str:
    """One OTP request against a real account. Returns its request id."""
    user = await env.create_user(roles=("super_admin",))
    asked = await env.client.post(
        f"{ADMIN_AUTH}/otp/request", json={"mobile_number": user.mobile_number}
    )
    assert asked.status_code == 202, asked.text
    return asked.json()["request_id"]


async def stored(env, request_id: str) -> OtpChallenge:
    async with env.sessions() as db:
        return await db.get(OtpChallenge, request_id)


async def logs(env, token: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    response = await env.get(f"{OTP_LOGS}?{query}" if query else OTP_LOGS, token)
    assert response.status_code == 200, response.text
    return response.json()


def row_for(listing: dict, request_id: str) -> dict:
    return next(row for row in listing["items"] if row["request_id"] == request_id)


# --- Switched on ----------------------------------------------------------------------------------


async def test_the_code_is_stored_in_the_clear(env):
    request_id = await a_challenge(env)

    challenge = await stored(env, request_id)

    assert challenge.otp_plain is not None
    assert challenge.otp_plain.isdigit()


async def test_the_screen_shows_the_code(env):
    token = await an_admin(env)
    request_id = await a_challenge(env)

    listing = await logs(env, token, limit=100)

    assert row_for(listing, request_id)["otp"] == (await stored(env, request_id)).otp_plain


async def test_the_shown_code_actually_signs_in(env):
    """What the screen is for: read it, type it, you are in."""
    token = await an_admin(env)
    user = await env.create_user(roles=("super_admin",))
    asked = await env.client.post(
        f"{ADMIN_AUTH}/otp/request", json={"mobile_number": user.mobile_number}
    )
    request_id = asked.json()["request_id"]

    code = row_for(await logs(env, token, limit=100), request_id)["otp"]

    signed_in = await env.client.post(
        f"{ADMIN_AUTH}/otp/verify", json={"request_id": request_id, "otp": code}
    )
    assert signed_in.status_code == 200, signed_in.text


async def test_the_hash_is_still_written(env):
    """The plaintext sits beside the hash; it does not replace it."""
    request_id = await a_challenge(env)

    challenge = await stored(env, request_id)

    assert challenge.otp_hash.startswith("$")
    assert challenge.otp_hash != challenge.otp_plain


async def test_revealing_codes_gets_its_own_audit_event(env):
    """"Looked at delivery statuses" and "read live codes" must not read the same."""
    token = await an_admin(env)
    await a_challenge(env)

    await logs(env, token, limit=100)

    async with env.sessions() as db:
        from sqlalchemy import select

        from app.modules.audit_logs.models import AuditLog

        events = set(
            (
                await db.scalars(
                    select(AuditLog.event_type).where(
                        AuditLog.event_type.like("authentication.otp_%")
                    )
                )
            ).all()
        )
    assert "authentication.otp_codes_revealed" in events


# --- Switched off, which is the default ------------------------------------------------------------


class TestWithTheSwitchOff:
    @pytest.fixture
    def settings_overrides(self) -> dict:
        return {"otp_log_plaintext_enabled": False}

    async def test_nothing_is_stored(self, env):
        request_id = await a_challenge(env)

        assert (await stored(env, request_id)).otp_plain is None

    async def test_the_screen_shows_no_code(self, env):
        token = await an_admin(env)
        request_id = await a_challenge(env)

        listing = await logs(env, token, limit=100)

        assert row_for(listing, request_id)["otp"] is None

    async def test_sign_in_still_works(self, env):
        """The hash is what verification reads, so the switch cannot break logging in."""
        user = await env.create_user(roles=("super_admin",))

        login = await env.sign_in(ADMIN_AUTH, user.mobile_number)

        assert login["token"]["access_token"]
