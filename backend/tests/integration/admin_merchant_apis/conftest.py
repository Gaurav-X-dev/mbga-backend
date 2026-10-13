import pytest

from tests.integration.authentication.conftest import (  # noqa: F401
    AuthEnv,
    _prepared_database,
    code_of,
    database_url,
    env,
    random_mobile,
)
from tests.integration.deliveries.conftest import (  # noqa: F401
    ready_to_dispatch,
    settings_overrides,
)

pytestmark = [pytest.mark.integration, pytest.mark.mysql]
