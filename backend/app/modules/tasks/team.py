"""The people a task may be given to: this merchant's staff and its delivery crew.

There is no "task user" concept and this does not create one. The Assign To picker and the
`@mention` autocomplete both need the same thing the rest of the platform already has: the
people who work for the caller's merchant. So this is a query, not a table.

**Office staff only.** Drivers and helpers are `delivery_profiles` and are deliberately not
here: the delivery app has no task screen, so a task given to a driver is a task nobody can
see. Their work reaches them as delivery slips, not as tasks.

**A customer is never on this list either.** It is an internal board. One person can hold several
roles - the same mobile registered as a customer and later added as staff - and such a user
*does* belong here, as staff; but somebody whose only standing with this merchant is that they
buy gas from them does not, and used to appear with "Customer" written under their name.

Resolving a person's **role** takes a three-table join (`merchant_users` -> `user_roles` ->
`roles`), which is why it lives here rather than being repeated in the service: every task write
needs a name, and the list screen needs a name and a role for everyone at once.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole

ACTIVE = "ACTIVE"
#: A role that signs in on the customer app and nowhere else. Holding one is not a reason to
#: appear on an internal board - and holding one *as well as* a staff role is not a reason to be
#: left off it, which is why this filters people with no other standing rather than the role.
CUSTOMER_ROLE = "customer"
#: What a staff member is called when no role resolves. Never shown in practice - every merchant
#: user is created with one - but a blank chip on the picker would be worse than a word.
UNKNOWN_ROLE = "STAFF"


@dataclass(frozen=True)
class TeamMember:
    id: str
    name: str
    role: str
    branch_name: str | None


class TeamDirectory:
    """Reads one merchant's active staff."""

    def __init__(self, session: AsyncSession, merchant_id: str) -> None:
        self.session = session
        self.merchant_id = merchant_id

    def _internal_ids(self):
        """The office staff of this merchant.

        One subquery, used by the picker and by the membership test behind every assignment, so
        the two can never disagree about who may be given a task.

        Delivery crew are not included. They have no `merchant_users` row, and the delivery app
        has no task screen to show them one - a task assigned to a driver would sit unread.
        """
        return select(MerchantUser.user_id).where(
            MerchantUser.merchant_id == self.merchant_id,
            MerchantUser.status == ACTIVE,
        )

    async def members(self, *, search: str | None = None) -> list[TeamMember]:
        """Active staff of this merchant, for the picker (spec #1).

        Ordered by name so the picker is scannable and does not reorder between opens.
        """
        statement = (
            select(
                User.id,
                User.full_name,
                User.username,
                Merchant.name.label("branch"),
                MerchantUser.staff_type.label("staff_type"),
            )
            .join(MerchantUser, MerchantUser.user_id == User.id)
            .join(Merchant, Merchant.id == MerchantUser.merchant_id)
            .where(
                MerchantUser.merchant_id == self.merchant_id,
                MerchantUser.status == ACTIVE,
                User.status == ACTIVE,
            )
            .order_by(User.full_name, User.id)
        )
        term = (search or "").strip()
        if term:
            pattern = f"%{term}%"
            statement = statement.where(
                or_(User.full_name.like(pattern), User.username.like(pattern))
            )
        rows = list(await self.session.execute(statement))
        roles = await self._roles({row.id for row in rows})
        return [
            TeamMember(
                id=row.id,
                name=_display(row.full_name, row.username),
                # The job title the office chose when they added this person, which is the
                # answer to "what do they do here". Every merchant user was assigned the
                # `manager` role regardless of it, so reading the role alone called an
                # accountant a manager - and a person with no role at all nothing.
                role=_job_title(row.staff_type) or roles.get(row.id, UNKNOWN_ROLE),
                branch_name=row.branch,
            )
            for row in rows
        ]

    async def active_ids(self, user_ids: list[str]) -> set[str]:
        """Which of these are active staff of this merchant.

        The membership test behind every assignment and mention. One query for the whole list, so
        assigning ten people is one round trip rather than ten.
        """
        if not user_ids:
            return set()
        rows = await self.session.scalars(
            select(User.id).where(
                User.id.in_(user_ids),
                User.status == ACTIVE,
                User.id.in_(self._internal_ids()),
            )
        )
        return set(rows)

    async def names(self, user_ids: list[str] | set[str]) -> dict[str, str]:
        """Display names, for activity lines and denormalised columns.

        Always resolved from the users table, never from the request: the spec is explicit that a
        client's copy of a name can be stale, and an activity log that quotes a name the client
        sent is a log that can be written to say anything.
        """
        ids = list(user_ids)
        if not ids:
            return {}
        rows = list(
            await self.session.execute(
                select(User.id, User.full_name, User.username).where(User.id.in_(ids))
            )
        )
        return {row.id: _display(row.full_name, row.username) for row in rows}

    async def _roles(self, user_ids: set[str]) -> dict[str, str]:
        """One role code per user, and never the customer one.

        A user with several takes the first by code, so the picker is deterministic rather than
        showing whichever row the database returned first. `customer` is left out of that
        choice because it sorts before every staff role: a manager who also buys gas from their
        own agency - the same mobile registered twice - was listed on the internal board with
        "Customer" written under their name.
        """
        if not user_ids:
            return {}
        now = datetime.now(UTC).replace(tzinfo=None)
        rows = list(
            await self.session.execute(
                select(UserRole.user_id, func.min(Role.code).label("code"))
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    UserRole.user_id.in_(user_ids),
                    Role.code != CUSTOMER_ROLE,
                    UserRole.is_active.is_(True),
                    Role.is_active.is_(True),
                    or_(UserRole.valid_from.is_(None), UserRole.valid_from <= now),
                    or_(UserRole.valid_until.is_(None), UserRole.valid_until >= now),
                )
                .group_by(UserRole.user_id)
            )
        )
        return {row.user_id: (row.code or UNKNOWN_ROLE).upper() for row in rows}


def _job_title(staff_type: str | None) -> str:
    """`"ACCOUNTANT"` from whatever the panel stored, or `""` when it stored nothing."""
    return (staff_type or "").strip().upper().replace(" ", "_")


def _display(full_name: str | None, username: str | None) -> str:
    """The same rule `shared/business/actor.py` uses, so one person reads the same everywhere."""
    return full_name or username or "Unknown user"
