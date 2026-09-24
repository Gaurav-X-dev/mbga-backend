"""Database-backed authentication tests.

Runs the real app against the disposable MySQL/MariaDB database in TEST_DATABASE_URL (its name must
contain "test"). Only synthetic data is used; every table touched here is emptied before the run.
"""

import os
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.app import get_settings
from app.main import app
from app.modules.authentication.dependencies import get_otp_provider
from app.modules.customers.models import CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.permissions.models import Permission
from app.modules.roles.models import Role, RoleLoginChannel, RolePermission
from app.modules.constants.seeds import ConstantsSeedRunner
from app.modules.roles.seed_runner import RBACSeedRunner
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.shared.database.session import get_db_session
from app.shared.otp.provider import OTPDeliveryError, OTPDeliveryProvider, OTPDeliveryResult

pytestmark = [pytest.mark.integration, pytest.mark.mysql]

TEST_OTP = "4826"
DATA_TABLES = [
    "auth_throttle_events",
    "audit_logs",
    "login_sessions",
    "otp_challenges",
    # Orders, expenses and pricing hang off merchants and customer_profiles, so they
    # are emptied before them.
    "order_status_history",
    "order_items",
    "orders",
    "order_number_sequences",
    "idempotency_keys",
    "notification_outbox",
    "expenses",
    "expense_categories",
    "customer_price_override_logs",
    "customer_price_overrides",
    "pricing_change_logs",
    "pricing_entries",
    "pricing_months",
    "customer_documents",
    "customer_profiles",
    "delivery_profiles",
    "merchant_users",
    "user_roles",
    "merchants",
    "users",
]


def _env_file_value(name: str) -> str | None:
    path = Path(".env")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return None


def _test_database_url() -> str | None:
    return os.getenv("TEST_DATABASE_URL") or _env_file_value("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is absent; database-backed auth tests skipped")
    lowered = url.lower()
    if not lowered.startswith("mysql+asyncmy://") or "test" not in lowered.rsplit("/", 1)[-1]:
        pytest.fail("TEST_DATABASE_URL must be a disposable mysql+asyncmy database whose name contains 'test'")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        cfg = Config(str(Path("alembic.ini")))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return url


class CapturingOTPProvider(OTPDeliveryProvider):
    """Records deliveries in memory instead of sending SMS."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail_with: OTPDeliveryError | None = None

    async def send_otp(self, **kwargs) -> OTPDeliveryResult:
        if self.fail_with:
            raise self.fail_with
        self.sent.append(kwargs)
        return OTPDeliveryResult(provider="capture", reference=f"ref-{len(self.sent)}")


@dataclass
class AuthEnv:
    client: httpx.AsyncClient
    sessions: async_sessionmaker
    provider: CapturingOTPProvider
    settings: object
    created: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- data

    async def role(self, code: str) -> Role:
        async with self.sessions() as db:
            return await db.scalar(select(Role).where(Role.code == code))

    async def create_user(self, *, status: str = "ACTIVE", roles: tuple[str, ...] = (), mobile: str | None = None, name: str = "Test User") -> User:
        now = datetime.now(UTC)
        user = User(
            id=str(uuid4()),
            full_name=name,
            mobile_number=mobile or random_mobile(),
            country_code="+91",
            role=roles[0] if roles else "customer",
            status=status,
            created_at=now,
            updated_at=now,
        )
        async with self.sessions() as db:
            db.add(user)
            await db.flush()
            for code in roles:
                await self._assign(db, user.id, code)
            await db.commit()
        return user

    async def assign_role(self, user_id: str, code: str, *, scope: tuple[str, str] = ("global", "global")) -> None:
        async with self.sessions() as db:
            await self._assign(db, user_id, code, scope)
            await db.commit()

    async def _assign(self, db: AsyncSession, user_id: str, code: str, scope: tuple[str, str] = ("global", "global")) -> None:
        role = await db.scalar(select(Role).where(Role.code == code))
        db.add(
            UserRole(
                id=str(uuid4()),
                user_id=user_id,
                role_id=role.id,
                assigned_at=datetime.now(UTC),
                is_active=True,
                scope_type=scope[0],
                scope_id=scope[1],
            )
        )

    async def create_role(self, code: str, channel: str, permissions: list[str]) -> None:
        now = datetime.now(UTC)
        async with self.sessions() as db:
            if await db.scalar(select(Role).where(Role.code == code)):
                return
            role = Role(id=str(uuid4()), name=code, code=code, role_type="custom", is_system=False, is_active=True, created_at=now, updated_at=now)
            db.add(role)
            await db.flush()
            db.add(RoleLoginChannel(role_id=role.id, login_channel=channel, is_allowed=True, created_at=now))
            for permission_code in permissions:
                permission = await db.scalar(select(Permission).where(Permission.code == permission_code))
                db.add(RolePermission(role_id=role.id, permission_id=permission.id, granted_at=now))
            await db.commit()

    async def create_merchant(self, *, status: str = "ACTIVE", approval_status: str = "APPROVED") -> Merchant:
        now = datetime.now(UTC)
        merchant = Merchant(
            id=str(uuid4()),
            code=f"T-{uuid4().hex[:10].upper()}",
            name="Test Gas Agency",
            status=status,
            approval_status=approval_status,
            created_at=now,
            updated_at=now,
        )
        async with self.sessions() as db:
            db.add(merchant)
            await db.commit()
        return merchant

    async def create_merchant_staff(self, merchant: Merchant | None = None, *, roles: tuple[str, ...] = ("manager",), link_status: str = "ACTIVE") -> tuple[User, Merchant]:
        merchant = merchant or await self.create_merchant()
        user = await self.create_user(roles=roles, name="Test Manager")
        now = datetime.now(UTC)
        async with self.sessions() as db:
            db.add(MerchantUser(id=str(uuid4()), merchant_id=merchant.id, user_id=user.id, staff_type="PRIMARY_MANAGER", status=link_status, created_at=now, updated_at=now))
            await db.commit()
        return user, merchant

    async def create_delivery_user(
        self,
        merchant: Merchant | None = None,
        *,
        kind: str = "DRIVER",
        status: str = "ACTIVE",
        approval_status: str = "APPROVED",
    ) -> tuple[User, Merchant, DeliveryProfile]:
        merchant = merchant or await self.create_merchant()
        user = await self.create_user(roles=("driver" if kind == "DRIVER" else "helper",), name="Test Driver")
        now = datetime.now(UTC)
        profile = DeliveryProfile(
            id=str(uuid4()),
            merchant_id=merchant.id,
            user_id=user.id,
            delivery_user_type=kind,
            employee_code=f"E-{uuid4().hex[:8]}",
            status=status,
            approval_status=approval_status,
            created_at=now,
            updated_at=now,
        )
        async with self.sessions() as db:
            db.add(profile)
            await db.commit()
        return user, merchant, profile

    async def execute(self, statement, params: dict | None = None):
        async with self.sessions() as db:
            result = await db.execute(statement, params or {})
            await db.commit()
            return result

    async def scalar(self, statement):
        async with self.sessions() as db:
            return await db.scalar(statement)

    async def customer_profile(self, mobile: str) -> CustomerProfile | None:
        return await self.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))

    # ---------------------------------------------------------------- flows

    async def request_code(self, prefix: str, mobile: str, **extra) -> httpx.Response:
        return await self.client.post(f"{prefix}/otp/request", json={"mobile_number": mobile, **extra})

    def last_code(self, mobile: str | None = None) -> str:
        sent = [item for item in self.provider.sent if mobile is None or item["mobile_number"] == mobile]
        return sent[-1]["otp"] if sent else TEST_OTP

    def sent_to(self, mobile: str) -> int:
        return sum(1 for item in self.provider.sent if item.get("mobile_number") == mobile)

    async def sign_in(self, prefix: str, mobile: str, *, device_id: str | None = None) -> dict:
        request = await self.request_code(prefix, mobile)
        assert request.status_code == 202, request.text
        body = {"request_id": request.json()["request_id"], "otp": self.last_code(mobile)}
        if device_id:
            body["device"] = {"device_id": device_id, "device_type": "android"}
        verify = await self.client.post(f"{prefix}/otp/verify", json=body)
        assert verify.status_code == 200, verify.text
        return verify.json()

    async def verify(self, prefix: str, mobile: str) -> httpx.Response:
        request = await self.request_code(prefix, mobile)
        assert request.status_code == 202, request.text
        return await self.client.post(f"{prefix}/otp/verify", json={"request_id": request.json()["request_id"], "otp": self.last_code(mobile)})

    async def get(self, path: str, token: str | None = None, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await self.client.get(path, headers=headers, **kwargs)

    async def post(self, path: str, token: str | None = None, json: dict | None = None, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return await self.client.post(path, headers=headers, json=json, **kwargs)


def random_mobile() -> str:
    return f"+917{random.randint(100000000, 999999999)}"


def random_ip() -> str:
    # Documentation range (RFC 5737); each test gets its own client address for the per-IP limits.
    return f"198.51.{random.randint(0, 255)}.{random.randint(1, 254)}"


def new_client(ip: str | None = None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False, client=(ip or random_ip(), 50000))
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def code_of(response: httpx.Response) -> str | None:
    detail = response.json().get("detail") if response.content else None
    return detail.get("code") if isinstance(detail, dict) else None


@pytest.fixture(scope="session")
def _prepared_database(database_url: str) -> str:
    import asyncio

    async def prepare() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.begin() as connection:
            existing = set((await connection.execute(text("SHOW TABLES"))).scalars().all())
            await connection.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for table in DATA_TABLES:
                if table in existing:
                    await connection.execute(text(f"DELETE FROM {table}"))
            await connection.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with sessions() as db:
            await RBACSeedRunner(db).run()
            await ConstantsSeedRunner(db).run()
        await engine.dispose()

    asyncio.run(prepare())
    return database_url


@pytest.fixture
def settings_overrides() -> dict:
    return {}


@pytest.fixture
async def env(_prepared_database: str, settings_overrides: dict):
    engine = create_async_engine(_prepared_database, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    provider = CapturingOTPProvider()
    settings = get_settings().model_copy(
        update={
            "dev_fixed_otp_enabled": True,
            "dev_fixed_otp_code": TEST_OTP,
            "otp_length": 4,
            "otp_resend_cooldown_seconds": 30,
            # Pinned so the suite does not depend on the limits a developer sets in their own .env.
            "otp_max_requests_per_hour": 5,
            "dev_expose_otp_in_response": False,
            **settings_overrides,
        }
    )

    async def test_session():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db_session] = test_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_otp_provider] = lambda: provider
    async with new_client() as client:
        yield AuthEnv(client=client, sessions=sessions, provider=provider, settings=settings)
    app.dependency_overrides.clear()
    await engine.dispose()
