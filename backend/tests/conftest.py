"""Suite-wide configuration.

`FCM_ENABLED` is forced off before anything reads the settings. A developer's `.env` may
well have push switched on, and the auto-dispatch fires on every request that queues a
notification - the suite would then make a real Firebase call per test, which is slow,
flaky and reaches the network from a unit test run. The dispatcher's own behaviour is
covered directly in `tests/integration/notifications` with a stubbed client.

An environment variable rather than an edit to `.env`: pydantic-settings reads the
environment ahead of the file, so this wins without touching anyone's local config.
"""

import os

os.environ["FCM_ENABLED"] = "false"

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
