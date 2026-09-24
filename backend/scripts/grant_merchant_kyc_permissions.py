"""Grant the customer and KYC permissions to a merchant role in THIS deployment.

Why this is a script and not part of the RBAC seed
--------------------------------------------------
The seed deliberately gives the `manager` role no authority over customer records, and the
test suite asserts that a plain Manager cannot approve a customer. That encodes a real
decision: who may approve a customer is granted per deployment, not implied by a job title.

So the grant lives here. Running it is an explicit act with an audit trail, and the seed keeps
its meaning.

    python scripts/grant_merchant_kyc_permissions.py --dry-run
    python scripts/grant_merchant_kyc_permissions.py --execute

Add --role salesperson to grant the narrower set instead.
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

# What each role needs to work the customer and KYC screens end to end.
GRANTS: dict[str, tuple[str, ...]] = {
    # SRS FR-CM-05: reviews customer registrations and decides on them.
    "manager": (
        "customers.view",
        "customers.create",
        "customers.update",
        "customers.review",
        "customers.approve",
        "customers.reject",
        "customer_documents.view",
        "customer_documents.review",
        # The Create Order screen calls the eligibility endpoint, which is behind this.
        "orders.create",
    ),
    # Spec 7.1: adds customers, but does not decide on them. No approve or reject.
    "salesperson": (
        "customers.view",
        "customers.create",
        "orders.create",
    ),
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
        print(f"Role      : {role_code}")
        print(f"Already has: {sorted(set(wanted) & held) or '(none)'}")
        print(f"To grant   : {missing or '(nothing — already complete)'}")

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
