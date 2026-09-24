"""Remove records created by the web panel's Playwright E2E tests.

Local/development/test only. Dry run by default; pass --apply to delete.

Selection rule (every condition must hold):

* Merchant: code starts with "E2E-", business name starts with "E2E ", and the email is
  empty or ends with "@example.invalid".
* Delivery team members and merchant staff links: belong to a selected merchant.
* User: linked to a selected merchant, full name starts with "E2E ", not linked to any other
  merchant or customer profile, and has no role assignment outside the selected merchants.
* Sign-in sessions of selected users are removed. Audit log history is kept.

The script aborts (and deletes nothing) if a selected merchant has customer profiles.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import and_, delete, func, or_, select

from app.config.app import Settings, get_settings
from app.modules.authentication.models import LoginSession
from app.modules.customers.models import CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.database.session import AsyncSessionLocal

SAFE_ENVIRONMENTS = {"local", "development", "dev", "test"}
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1"}
E2E_CODE_PREFIX = "E2E-"
E2E_NAME_PREFIX = "E2E "
E2E_EMAIL_SUFFIX = "@example.invalid"


def ensure_safe_target(settings: Settings) -> None:
    """Refuse to run anywhere except a local development/test database."""
    if settings.app_env.lower() not in SAFE_ENVIRONMENTS:
        raise SystemExit(f"Refusing to clean E2E data: APP_ENV={settings.app_env!r} is not local/development/test.")
    host = urlparse(settings.database_url).hostname or ""
    if host.lower() not in LOCAL_DATABASE_HOSTS:
        raise SystemExit("Refusing to clean E2E data: the database is not on this computer.")


def mask_mobile(mobile: str | None) -> str:
    if not mobile:
        return "-"
    return f"{mobile[:3]}******{mobile[-4:]}"


@dataclass
class Selection:
    merchants: list[Merchant] = field(default_factory=list)
    delivery_profiles: list[DeliveryProfile] = field(default_factory=list)
    merchant_links: list[MerchantUser] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    kept_users: list[User] = field(default_factory=list)
    customer_profiles: int = 0
    sessions: int = 0

    @property
    def merchant_ids(self) -> list[str]:
        return [merchant.id for merchant in self.merchants]

    @property
    def user_ids(self) -> list[str]:
        return [user.id for user in self.users]


async def select_e2e_data(session) -> Selection:
    selection = Selection()
    selection.merchants = list(
        (
            await session.execute(
                select(Merchant).where(
                    Merchant.code.like(f"{E2E_CODE_PREFIX}%"),
                    Merchant.name.like(f"{E2E_NAME_PREFIX}%"),
                    or_(Merchant.email.is_(None), Merchant.email.like(f"%{E2E_EMAIL_SUFFIX}")),
                )
            )
        )
        .scalars()
        .all()
    )
    merchant_ids = selection.merchant_ids
    if not merchant_ids:
        return selection

    selection.delivery_profiles = list(
        (await session.execute(select(DeliveryProfile).where(DeliveryProfile.merchant_id.in_(merchant_ids)))).scalars().all()
    )
    selection.merchant_links = list(
        (await session.execute(select(MerchantUser).where(MerchantUser.merchant_id.in_(merchant_ids)))).scalars().all()
    )
    selection.customer_profiles = int(
        await session.scalar(
            select(func.count()).select_from(CustomerProfile).where(CustomerProfile.merchant_id.in_(merchant_ids))
        )
        or 0
    )

    candidate_ids = {profile.user_id for profile in selection.delivery_profiles} | {
        link.user_id for link in selection.merchant_links
    }
    candidates = list((await session.execute(select(User).where(User.id.in_(candidate_ids)))).scalars().all()) if candidate_ids else []
    for user in candidates:
        other_merchant_links = await session.scalar(
            select(func.count())
            .select_from(MerchantUser)
            .where(MerchantUser.user_id == user.id, MerchantUser.merchant_id.not_in(merchant_ids))
        )
        other_delivery = await session.scalar(
            select(func.count())
            .select_from(DeliveryProfile)
            .where(DeliveryProfile.user_id == user.id, DeliveryProfile.merchant_id.not_in(merchant_ids))
        )
        customer = await session.scalar(
            select(func.count()).select_from(CustomerProfile).where(CustomerProfile.user_id == user.id)
        )
        other_roles = await session.scalar(
            select(func.count())
            .select_from(UserRole)
            .where(
                UserRole.user_id == user.id,
                ~and_(UserRole.scope_type == "merchant", UserRole.scope_id.in_(merchant_ids)),
            )
        )
        is_e2e_name = (user.full_name or "").startswith(E2E_NAME_PREFIX)
        if is_e2e_name and not (other_merchant_links or other_delivery or customer or other_roles):
            selection.users.append(user)
        else:
            selection.kept_users.append(user)

    if selection.user_ids:
        selection.sessions = int(
            await session.scalar(
                select(func.count()).select_from(LoginSession).where(LoginSession.user_id.in_(selection.user_ids))
            )
            or 0
        )
    return selection


def report(selection: Selection) -> None:
    print("E2E test data selection")
    print(f"  merchants:            {len(selection.merchants)}")
    for merchant in selection.merchants:
        print(f"    - {merchant.code} | {merchant.name} | {mask_mobile(merchant.mobile_number)}")
    print(f"  delivery team members: {len(selection.delivery_profiles)}")
    for profile in selection.delivery_profiles:
        print(f"    - {profile.delivery_user_type} {profile.employee_code}")
    print(f"  merchant staff links:  {len(selection.merchant_links)}")
    print(f"  users to delete:       {len(selection.users)}")
    for user in selection.users:
        print(f"    - {user.full_name} | {mask_mobile(user.mobile_number)}")
    print(f"  sign-in sessions:      {selection.sessions}")
    if selection.kept_users:
        print(f"  users kept (linked to non-E2E data or not named 'E2E ...'): {len(selection.kept_users)}")
    if selection.customer_profiles:
        print(f"  customer profiles on selected merchants: {selection.customer_profiles} (cleanup will abort)")


async def apply(session, selection: Selection) -> None:
    merchant_ids = selection.merchant_ids
    user_ids = selection.user_ids
    kept_ids = [user.id for user in selection.kept_users]
    await session.execute(delete(DeliveryProfile).where(DeliveryProfile.merchant_id.in_(merchant_ids)))
    await session.execute(delete(MerchantUser).where(MerchantUser.merchant_id.in_(merchant_ids)))
    # Role assignments scoped to the removed merchants (for deleted and kept users alike).
    await session.execute(
        delete(UserRole).where(UserRole.scope_type == "merchant", UserRole.scope_id.in_(merchant_ids))
    )
    if user_ids:
        await session.execute(delete(LoginSession).where(LoginSession.user_id.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.execute(delete(Merchant).where(Merchant.id.in_(merchant_ids)))
    if kept_ids:
        print(f"Kept {len(kept_ids)} user account(s); only their roles for the removed merchants were removed.")


async def main(apply_changes: bool) -> int:
    ensure_safe_target(get_settings())
    async with AsyncSessionLocal() as session:
        selection = await select_e2e_data(session)
        report(selection)
        if not selection.merchants:
            print("Nothing to clean.")
            return 0
        if selection.customer_profiles:
            print("Aborted: selected merchants have customer profiles. Nothing was deleted.")
            return 2
        if not apply_changes:
            print("Dry run only. Re-run with --apply to delete exactly the records listed above.")
            return 0
        try:
            await apply(session, selection)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        print("E2E test data removed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="delete the selected records")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.apply)))
