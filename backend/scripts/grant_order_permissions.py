"""Grant the order permissions to a merchant role in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
The `orders.*` permissions are already seeded, but the seed deliberately keeps `manager`
narrow and the test suite asserts that. Who may see and place orders is a per-deployment
decision, the same rule `grant_merchant_kyc_permissions.py`, `grant_pricing_permissions.py`
and `grant_expense_permissions.py` follow.

The grants below are spec §2.1's role matrix:

    permission      MANAGER  SALESPERSON  GODOWN_INCHARGE  ACCOUNTANT
    orders.view        x          x              x              x
    orders.create      x          x
    orders.update      x          x

`orders.update` is what accepts a placed order (`POST /orders/{id}/confirm`). It is not in the
spec's matrix either - §2.1 lists no "confirm an order" right - but the status exists in §6.1 and
somebody has to be able to reach it, so it goes to the two roles that already take orders.

`orders.cancel` is not in that matrix - the cancel route is an addition on top of the
spec's six endpoints - so it goes to `manager` only, the role that already carries the
authority to undo things.

    python scripts/grant_order_permissions.py --dry-run
    python scripts/grant_order_permissions.py --execute
    python scripts/grant_order_permissions.py --role salesperson --execute
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.app import get_settings
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RolePermission

GRANTS: dict[str, tuple[str, ...]] = {
    # Runs the Orders tab and the Create Order screen, accepts orders, and may undo one.
    "manager": ("orders.view", "orders.create", "orders.update", "orders.cancel"),
    # Places orders for customers and accepts them, but does not cancel them.
    "salesperson": ("orders.view", "orders.create", "orders.update"),
    # Reads the order queue to prepare cylinders; does not place or cancel.
    "godown_stock_manager": ("orders.view",),
    # Reads orders for billing and reconciliation only.
    "accountant": ("orders.view",),
}


async def grant(role_code: str, execute: bool) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    added = 0
    async with async_sessionmaker(engine, class_=AsyncSession)() as db:
        role = await db.scalar(select(Role).where(Role.code == role_code))
        if role is None:
            print(f"Role {role_code!r} does not exist. Run scripts/seed_rbac.py first.")
            await engine.dispose()
            return 1

        wanted = GRANTS[role_code]
        held = set(
            (
                await db.execute(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                )
            ).scalars()
        )
        missing = [code for code in wanted if code not in held]
        print(f"Role       : {role_code}")
        print(f"Already has: {sorted(set(wanted) & held) or '(none)'}")
        print(f"To grant   : {missing or '(nothing - already complete)'}")

        if not missing:
            await engine.dispose()
            return 0
        if not execute:
            print("\nDry run. Re-run with --execute to apply.")
            await engine.dispose()
            return 0

        now = datetime.now(UTC)
        for code in missing:
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            if permission is None:
                print(f"  skipped {code}: permission not seeded")
                continue
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id,
                    granted_at=now,
                    granted_by=None,
                )
            )
            added += 1
        await db.commit()
        print(f"\nGranted {added} permission(s).")
        print("Staff already signed in keep their old permissions until the cache expires")
        print(f"(PERMISSION_CACHE_TTL_SECONDS={settings.permission_cache_ttl_seconds}) or they sign in again.")
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(GRANTS), default="manager")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Show what would change (default).")
    action.add_argument("--execute", action="store_true", help="Apply the grants.")
    args = parser.parse_args()
    return asyncio.run(grant(args.role, execute=args.execute))


if __name__ == "__main__":
    raise SystemExit(main())
