"""Canonical mobile identity creation shared by every application channel."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


async def get_or_create_mobile_user(
    session: AsyncSession,
    *,
    mobile: str,
    full_name: str | None,
    email: str | None = None,
    legacy_role: str,
    new_user_status: str = "ACTIVE",
) -> tuple[User, bool]:
    """Return the one identity for ``mobile`` without granting any application role.

    Roles and merchant/customer/delivery profiles remain the responsibility of the
    calling workflow.  The nested transaction handles two channels attempting to
    create the same mobile at the same time once the database unique key is present.
    """
    user = await session.scalar(
        select(User).where(User.mobile_number == mobile).order_by(User.created_at, User.id).limit(1)
    )
    if user is not None:
        if not user.full_name and full_name:
            user.full_name = full_name
            user.updated_at = datetime.now(UTC)
        return user, False

    now = datetime.now(UTC)
    user = User(
        id=str(uuid4()),
        email=email.lower() if email else None,
        username=None,
        full_name=full_name,
        mobile_number=mobile,
        country_code="+91",
        password_hash=None,
        role=legacy_role,
        status=new_user_status,
        created_at=now,
        updated_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError:
        # A concurrent request won the unique-mobile race.  Reuse its identity.
        user = await session.scalar(select(User).where(User.mobile_number == mobile).limit(1))
        if user is None:
            raise
        return user, False
    return user, True
