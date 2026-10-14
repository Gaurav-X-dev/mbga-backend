"""Named accounts that sign in without an SMS.

The SMS credit ran out with one message left, and when it does nobody can sign in at all -
not a tester, not the office, not a customer. The ask was to print the OTP on an admin screen.
That cannot be done: the row keeps a one-way hash and nothing else, so there is no code to
print. Storing the plaintext instead would hand every account to whoever can open that screen.

This is the narrow version of the same need. A number on `OTP_TEST_NUMBERS` takes the fixed
`OTP_TEST_CODE` and is never sent a message; every other number is untouched and still gets a
random code over the provider. The list is the blast radius, and it is written by hand.
"""

import pytest

from tests.integration.authentication.conftest import (  # noqa: F401 - fixtures
    AuthEnv,
    _prepared_database,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql, pytest.mark.asyncio]

ADMIN_AUTH = "/api/v1/admin/auth"
TEST_CODE = "4321"


@pytest.fixture
def listed_number() -> str:
    """A fresh number each test: the rows outlive the test that made them."""
    return random_mobile()


@pytest.fixture
def settings_overrides(listed_number: str) -> dict:
    """A listed number and a code, as a deployment with no SMS credit would set them."""
    return {
        "otp_test_numbers": [listed_number],
        "otp_test_code": TEST_CODE,
        # Off, so nothing else is handing the code back and the test proves the list did it.
        "dev_fixed_otp_enabled": False,
        "dev_fixed_otp_code": None,
    }


async def an_account(env, mobile: str):
    """Staff rather than a customer: a customer also has to be approved, which is not the
    thing under test and would make these read as approval tests."""
    return await env.create_user(mobile=mobile, roles=("super_admin",))


async def request_code(env, mobile: str):
    return await env.client.post(f"{ADMIN_AUTH}/otp/request", json={"mobile_number": mobile})


async def verify(env, request_id: str, otp: str):
    return await env.client.post(
        f"{ADMIN_AUTH}/otp/verify", json={"request_id": request_id, "otp": otp}
    )


# --- A listed number ------------------------------------------------------------------------------


async def test_a_listed_number_signs_in_with_the_fixed_code(env, listed_number):
    await an_account(env, listed_number)
    asked = await request_code(env, listed_number)
    assert asked.status_code == 202, asked.text

    signed_in = await verify(env, asked.json()["request_id"], TEST_CODE)

    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["token"]["access_token"]


async def test_no_message_is_sent_for_a_listed_number(env, listed_number):
    """The whole point: it works when there is no credit left to send one."""
    await an_account(env, listed_number)

    await request_code(env, listed_number)

    assert env.provider.sent == [], "an SMS was sent to a test number"


async def test_the_row_says_the_message_was_skipped(env, listed_number):
    """Somebody reading the OTP log is working out why a code never arrived."""
    await an_account(env, listed_number)
    asked = await request_code(env, listed_number)

    async with env.sessions() as db:
        from app.modules.authentication.otp_models import OtpChallenge

        row = await db.get(OtpChallenge, asked.json()["request_id"])

    assert row.delivery_status == "TEST_BYPASS"
    assert row.delivery_provider == "test-number"


async def test_the_code_is_still_only_stored_hashed(env, listed_number):
    """A listed number is a shortcut for delivery, not for storage."""
    await an_account(env, listed_number)
    asked = await request_code(env, listed_number)

    async with env.sessions() as db:
        from app.modules.authentication.otp_models import OtpChallenge

        row = await db.get(OtpChallenge, asked.json()["request_id"])

    assert TEST_CODE not in row.otp_hash
    assert row.otp_hash.startswith("$"), "not a hash"


async def test_the_wrong_code_is_still_refused(env, listed_number):
    await an_account(env, listed_number)
    asked = await request_code(env, listed_number)

    refused = await verify(env, asked.json()["request_id"], "0000")

    assert refused.status_code >= 400


# --- Every other number is untouched -------------------------------------------------------------


async def test_an_unlisted_number_is_sent_a_real_message(env, listed_number):
    other = random_mobile()
    await an_account(env, other)

    await request_code(env, other)

    assert len(env.provider.sent) == 1
    assert env.provider.sent[0]["mobile_number"] == other


async def test_an_unlisted_number_does_not_take_the_test_code(env, listed_number):
    """Otherwise the list would be a master key rather than a list."""
    other = random_mobile()
    await an_account(env, other)
    asked = await request_code(env, other)

    refused = await verify(env, asked.json()["request_id"], TEST_CODE)

    assert refused.status_code >= 400, "the test code signed in an unlisted number"
