"""Create dedicated review-only accounts using the configured phones; no SMS is sent."""

import asyncio

from app import api as _model_registry  # noqa: F401
from app.config.app import get_settings
from app.modules.authentication.review_provisioning import provision_review_accounts
from app.shared.database.session import AsyncSessionLocal, engine


async def main():
    async with AsyncSessionLocal() as session:
        accounts = await provision_review_accounts(session, get_settings())
        for channel, phone in accounts.items():
            print(channel + " review account: " + phone)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
