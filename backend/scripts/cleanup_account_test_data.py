import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from app.config.app import get_settings
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.database.session import AsyncSessionLocal


# Current development numbers plus the invalid numbers used by earlier seed versions.
TEST_MOBILES = {
    "+919999900001",
    "+919999900002",
    "+919999900003",
    "+919999900004",
    "+910000000001",
    "+910000000002",
    "+910000000003",
    "+910000000004",
}


def _refuse_unsafe_environment() -> None:
    settings = get_settings()
    if settings.app_env.lower() not in {"local", "development", "test"}:
        raise SystemExit("Refusing to clean account test data outside local/development/test.")


async def main() -> None:
    _refuse_unsafe_environment()
    async with AsyncSessionLocal() as session:
        merchant = await session.scalar(select(Merchant).where(Merchant.code == "MBGA-TEST-M001"))
        user_ids = []
        result = await session.execute(select(User.id).where(User.mobile_number.in_(TEST_MOBILES)))
        user_ids.extend(result.scalars().all())
        if merchant:
            await session.execute(delete(DeliveryProfile).where(DeliveryProfile.merchant_id == merchant.id))
            await session.execute(delete(MerchantUser).where(MerchantUser.merchant_id == merchant.id))
            await session.delete(merchant)
        if user_ids:
            await session.execute(delete(UserRole).where(UserRole.user_id.in_(user_ids)))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.commit()
    print("Cleaned MBGA account test data.")


if __name__ == "__main__":
    asyncio.run(main())
