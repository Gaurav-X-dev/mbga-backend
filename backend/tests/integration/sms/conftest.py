"""Fixtures for the SMS provider wiring tests.

Re-exports the authentication suite's fixtures rather than rebuilding them. That conftest is
only imported here, never edited — and these tests live in their own package so the protected
212-test authentication baseline stays exactly measurable.
"""

import pytest

# Imported so pytest collects them as fixtures in this package.
from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    CapturingOTPProvider,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]


@pytest.fixture
def settings_overrides(request) -> dict:
    """Lets a test pin a setting with `@pytest.mark.parametrize(..., indirect=True)`.

    The authentication suite's version takes no parameter, so re-exporting it would make an
    indirect override silently do nothing.
    """
    return dict(getattr(request, "param", {}) or {})

CUSTOMER = "/api/v1/customer/auth"
REGISTRATION = "/api/v1/customer/registration"
MERCHANT = "/api/v1/merchant/auth"
DELIVERY = "/api/v1/delivery/auth"
ADMIN = "/api/v1/admin/auth"
