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
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

CUSTOMER = "/api/v1/customer/auth"
REGISTRATION = "/api/v1/customer/registration"
MERCHANT = "/api/v1/merchant/auth"
DELIVERY = "/api/v1/delivery/auth"
ADMIN = "/api/v1/admin/auth"
