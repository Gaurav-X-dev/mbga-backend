"""Three apps, three Firebase projects.

A device token is only valid in the project that minted it. The merchant app, the customer
app and the delivery app are three separate Firebase projects, so the routing key is **which
app registered the token**, not who the notification is addressed to.

Those two usually agree, and the case where they do not is the one worth pinning: the same
person signed into two apps holds two tokens in two projects, and sending either one through
the wrong project loses the notification.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.config.app import get_settings
from app.modules.authentication.models import LoginSession
from app.modules.notifications.fcm import SendResult
from app.modules.notifications.projects import FcmProjects
from tests.integration.notifications.conftest import customer, queue, staff
from tests.integration.notifications.test_dispatcher import StubFcm, StubProjects, _dispatch, _row

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

MERCHANT = "MERCHANT"
CUSTOMER = "CUSTOMER"
DELIVERY = "DELIVERY"


# --- Routing ------------------------------------------------------------------------------


async def test_a_merchant_token_goes_through_the_merchant_project(env):
    _token, merchant, _u = await staff(env, fcm_token="merchant-device")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    merchant_app, customer_app = StubFcm(project_id="mbga-merchant"), StubFcm(project_id="mbga-customer")

    await _dispatch(env, StubProjects(by_channel={MERCHANT: merchant_app, CUSTOMER: customer_app}))

    assert merchant_app.tokens == ["merchant-device"]
    assert customer_app.sent == [], "a merchant token must not be sent through the customer project"


async def test_a_customer_token_goes_through_the_customer_project(env):
    _staff_token, merchant, _u = await staff(env)
    _token, profile, _user = await customer(env, merchant, fcm_token="customer-device")
    await queue(env, recipient_kind="customer", recipient_id=profile.id)
    merchant_app, customer_app = StubFcm(project_id="mbga-merchant"), StubFcm(project_id="mbga-customer")

    await _dispatch(env, StubProjects(by_channel={MERCHANT: merchant_app, CUSTOMER: customer_app}))

    assert customer_app.tokens == ["customer-device"]
    assert merchant_app.sent == []


async def test_one_person_in_two_apps_is_reached_through_both_projects(env):
    """The case the recipient alone cannot answer: two tokens, two projects, one event."""
    _staff_token, merchant, user = await staff(env, fcm_token="their-merchant-phone")
    # The same user also holds a live customer-app session on another device.
    async with env.sessions() as session:
        original = await session.scalar(
            select(LoginSession).where(LoginSession.push_token == "their-merchant-phone")
        )
        session.add(
            LoginSession(
                id=str(uuid4()),
                user_id=user.id,
                refresh_token_hash=uuid4().hex,
                login_channel=CUSTOMER,
                session_type=original.session_type,
                push_token="their-customer-phone",
                created_at=original.created_at,
                expires_at=original.expires_at,
            )
        )
        await session.commit()
    await queue(env, recipient_kind="user", recipient_id=user.id)
    merchant_app, customer_app = StubFcm(project_id="mbga-merchant"), StubFcm(project_id="mbga-customer")

    report = await _dispatch(env, StubProjects(by_channel={MERCHANT: merchant_app, CUSTOMER: customer_app}))

    assert merchant_app.tokens == ["their-merchant-phone"]
    assert customer_app.tokens == ["their-customer-phone"]
    assert report.delivered == 1
    assert merchant


async def test_an_app_with_no_credential_is_skipped_not_fatal(env):
    """Bringing up one app's push must not hold the other two."""
    _manager, merchant, _u1 = await staff(env, fcm_token="configured-device")
    _colleague, _same, _u2 = await staff(env, merchant, fcm_token="unconfigured-device")
    async with env.sessions() as session:
        await session.execute(
            LoginSession.__table__.update()
            .where(LoginSession.__table__.c.push_token == "unconfigured-device")
            .values(login_channel=DELIVERY)
        )
        await session.commit()
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    merchant_app = StubFcm(project_id="mbga-merchant")

    report = await _dispatch(env, StubProjects(by_channel={MERCHANT: merchant_app, DELIVERY: None}))

    assert merchant_app.tokens == ["configured-device"]
    assert report.unconfigured == 1
    # One device got it, so the row is settled rather than retried for ever.
    assert report.delivered == 1
    assert (await _row(env, notification_id)).delivered_at is not None


async def test_with_no_app_configured_the_row_stays_queued(env):
    _token, merchant, _u = await staff(env, fcm_token="dev")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)

    report = await _dispatch(env, StubProjects(by_channel={MERCHANT: None}))

    assert report.unconfigured == 1
    row = await _row(env, notification_id)
    assert row.delivered_at is None, "nothing was sent, so nothing may be settled"
    assert "not configured" in (row.last_error or "")


# --- A token sent through the wrong project ----------------------------------------------


async def test_a_misrouted_token_is_kept_not_deleted(env):
    """`SENDER_ID_MISMATCH` means the configuration is wrong, not that the device is gone.

    Deleting the token would sign a working handset out of push until it was reinstalled,
    for a mistake in a credential path.
    """
    _token, merchant, _u = await staff(env, fcm_token="valid-but-misrouted")
    notification_id = await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    wrong_project = StubFcm(
        SendResult(ok=False, misrouted=True, error="400: SENDER_ID_MISMATCH"),
        project_id="mbga-customer",
    )

    report = await _dispatch(env, StubProjects(by_channel={MERCHANT: wrong_project}))

    assert report.misrouted == 1
    assert report.tokens_forgotten == 0, "the token is valid; only the routing was wrong"
    surviving = list(
        await env.execute(
            select(LoginSession.push_token).where(LoginSession.push_token == "valid-but-misrouted")
        )
    )
    assert surviving, "the token must still be there"
    # Retried, so fixing the credential mapping delivers the backlog.
    row = await _row(env, notification_id)
    assert row.delivered_at is None
    assert row.attempts == 1


async def test_a_genuinely_dead_token_is_still_forgotten(env):
    """The distinction only matters if the other branch still works."""
    _token, merchant, _u = await staff(env, fcm_token="uninstalled")
    await queue(env, recipient_kind="merchant", recipient_id=merchant.id)
    app = StubFcm(SendResult(ok=False, token_dead=True, error="404: UNREGISTERED"))

    report = await _dispatch(env, StubProjects(by_channel={MERCHANT: app}))

    assert report.tokens_forgotten == 1
    assert report.misrouted == 0


# --- The registry itself -------------------------------------------------------------------


def test_each_app_resolves_to_its_own_project():
    """The real credentials on disk, so a swapped path is caught here rather than in Firebase."""
    projects = FcmProjects(get_settings())

    ready = projects.configured()

    assert ready.get(MERCHANT) == "mbga-merchant"
    assert ready.get(CUSTOMER) == "mbga-customer"
    assert ready.get(DELIVERY) == "mbga-delivery-partner"


def test_an_unconfigured_app_falls_back_to_the_shared_credential():
    """A single-project deployment predates the split and must keep working."""
    settings = get_settings().model_copy(
        update={
            "fcm_credentials_merchant": None,
            "fcm_credentials_customer": None,
            "fcm_credentials_delivery": None,
            "fcm_credentials_file": "secrets/fcm-merchant.json",
        }
    )
    projects = FcmProjects(settings)

    assert projects.credential_path(CUSTOMER) == "secrets/fcm-merchant.json"
    assert projects.configured()[CUSTOMER] == "mbga-merchant"


def test_an_unknown_channel_resolves_to_nothing_rather_than_guessing():
    settings = get_settings().model_copy(
        update={
            "fcm_credentials_merchant": None,
            "fcm_credentials_customer": None,
            "fcm_credentials_delivery": None,
            "fcm_credentials_file": "",
        }
    )
    projects = FcmProjects(settings)

    assert projects.credential_path("ADMIN") is None
    assert projects.client_for("ADMIN") is None


def test_a_missing_credential_file_is_reported_not_raised():
    settings = get_settings().model_copy(
        update={"fcm_credentials_merchant": "secrets/does-not-exist.json", "fcm_credentials_file": ""}
    )
    projects = FcmProjects(settings)

    assert projects.client_for(MERCHANT) is None
    assert MERCHANT not in projects.configured()
