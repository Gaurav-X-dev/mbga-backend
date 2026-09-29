"""Repair rows stamped "Unknown user".

A customer's `users` row is created at their first OTP request, before they have told us
their name, so `full_name` is empty there. Everything that records who did something reads
that row - so until this was fixed, every order a self-registered customer placed or
cancelled was signed "Unknown user", even though their name was sitting in
`customer_profiles.owner_name` the whole time.

The code no longer does that: the actor now takes a customer's name from their profile, and
registration copies it onto the login. This repairs what was written before that.

Two passes, in this order:

1. **`users.full_name`** from the customer's profile. This is the root fix - it makes every
   future read correct without any further backfilling.
2. **Rows already stamped** with the placeholder. The name was copied onto them at the time,
   so fixing the user row does not reach back; each one is rewritten from whoever its
   `changed_by_user_id` points at.

Only the placeholder is touched. A row that carries a real name was correct when it was
written and is left exactly as it is.

    python scripts/backfill_actor_names.py            # dry run
    python scripts/backfill_actor_names.py --execute
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.modules.customers.models import CustomerProfile
from app.modules.orders.models import Order, OrderStatusHistory
from app.modules.users.models import User
from app.shared.database.session import AsyncSessionLocal

#: What `_display_name` falls back to when a user row has no name at all.
PLACEHOLDER = "Unknown user"


async def _name_the_logins(session, execute: bool) -> int:
    """Copy each customer's own name onto their login, where it is missing."""
    rows = (
        await session.execute(
            select(User, CustomerProfile)
            .join(CustomerProfile, CustomerProfile.user_id == User.id)
            .where((User.full_name.is_(None)) | (User.full_name == ""))
        )
    ).all()
    now = datetime.now(UTC)
    fixed = 0
    for user, profile in rows:
        name = profile.owner_name or profile.name
        if not name:
            print(f"  skipped user {user.id[:8]}: the profile has no name either")
            continue
        print(f"  users.full_name  {user.id[:8]} -> {name!r}")
        if execute:
            user.full_name = name
            user.updated_at = now
        fixed += 1
    return fixed


async def _restamp(session, execute: bool) -> int:
    """Rewrite history rows that carry the placeholder."""
    rows = list(
        await session.scalars(
            select(OrderStatusHistory).where(OrderStatusHistory.changed_by_name == PLACEHOLDER)
        )
    )
    # Resolved once per user rather than once per row: one customer usually owns several.
    names: dict[str, str | None] = {}
    fixed = 0
    for row in rows:
        user_id = row.changed_by_user_id
        if not user_id:
            print(f"  skipped history {row.id}: no user recorded, nothing to resolve from")
            continue
        if user_id not in names:
            names[user_id] = await _name_of(session, user_id)
        name = names[user_id]
        if not name:
            print(f"  skipped history {row.id}: user {user_id[:8]} has no name anywhere")
            continue
        order_number = await session.scalar(select(Order.order_number).where(Order.id == row.order_id))
        print(f"  history {row.id:>4} ({order_number} {row.status}) -> {name!r}")
        if execute:
            row.changed_by_name = name
        fixed += 1
    return fixed


async def _name_of(session, user_id: str) -> str | None:
    """The best name for a user: their login, then their customer profile."""
    user = await session.get(User, user_id)
    if user is not None and user.full_name:
        return user.full_name
    profile = await session.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user_id))
    if profile is None:
        return None
    return profile.owner_name or profile.name


async def _run(execute: bool) -> int:
    async with AsyncSessionLocal() as session:
        print("Naming logins that have no name:")
        named = await _name_the_logins(session, execute)
        if execute:
            # Flushed before the second pass so it can read the names just written.
            await session.flush()
        print(f"  -> {named} login(s)\n")

        print(f'Re-stamping history rows that say "{PLACEHOLDER}":')
        stamped = await _restamp(session, execute)
        print(f"  -> {stamped} row(s)\n")

        if not execute:
            print("Dry run. Re-run with --execute to apply.")
            return 0
        await session.commit()
        print("Done.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Apply the changes. Omit for a dry run.")
    args = parser.parse_args()
    return asyncio.run(_run(args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
