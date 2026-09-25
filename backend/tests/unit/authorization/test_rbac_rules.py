from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.authentication.constants import LoginChannel

pytestmark = pytest.mark.unit


@dataclass
class Assignment:
    permissions: set[str]
    user_active: bool = True
    role_active: bool = True
    permission_active: bool = True
    assignment_active: bool = True
    channel_allowed: bool = True
    valid_until: datetime | None = None


def calculate_fake_effective_permissions(assignment: Assignment) -> set[str]:
    now = datetime.now(UTC)
    if not assignment.user_active:
        return set()
    if not assignment.assignment_active:
        return set()
    if assignment.valid_until and assignment.valid_until <= now:
        return set()
    if not assignment.role_active:
        return set()
    if not assignment.permission_active:
        return set()
    if not assignment.channel_allowed:
        return set()
    return assignment.permissions


def test_inactive_role_behavior() -> None:
    assert calculate_fake_effective_permissions(Assignment({"orders.view"}, role_active=False)) == set()


def test_inactive_permission_behavior() -> None:
    assert calculate_fake_effective_permissions(Assignment({"orders.view"}, permission_active=False)) == set()


def test_expired_role_assignment_behavior() -> None:
    expired = datetime.now(UTC) - timedelta(minutes=1)
    assert calculate_fake_effective_permissions(Assignment({"orders.view"}, valid_until=expired)) == set()


def test_login_channel_restriction_behavior() -> None:
    assert calculate_fake_effective_permissions(Assignment({"orders.view"}, channel_allowed=False)) == set()


def test_customer_channel_is_not_admin_channel() -> None:
    assert LoginChannel.CUSTOMER != LoginChannel.ADMIN
