import secrets
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select, update

from app.config.app import Settings
from app.modules.authentication.constants import LoginChannel
from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.authentication.password_hasher import hash_secret, verify_secret
from app.modules.authentication.repository import AuthenticationRepository
from app.modules.authentication.schemas import (
    CurrentUserResponse,
    LogoutRequest,
    OTPRequest,
    OTPRequestResponse,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    TokenPair,
)
from app.modules.authentication.mobile_number import normalize_mobile_number
from app.modules.authentication.otp_service import OTPService
from app.modules.customers.models import CustomerDocument, CustomerProfile
from app.modules.delivery_users.models import DeliveryProfile
from app.modules.merchants.models import Merchant, MerchantUser
from app.modules.roles.models import Role
from app.modules.users.models import User
from app.modules.users.role_models import UserRole
from app.modules.users.role_repository import UserRoleRepository
from app.shared.otp.provider import OTPDeliveryProvider


class AuthenticationService:
    def __init__(
        self,
        repository: AuthenticationRepository,
        otp_service: OTPService,
        otp_provider: OTPDeliveryProvider,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.otp_service = otp_service
        self.otp_provider = otp_provider
        self.settings = settings

    async def request_otp(self, payload: OTPRequest, *, purpose: str | None = None, channel: LoginChannel | None = None) -> OTPRequestResponse:
        normalized_mobile = normalize_mobile_number(payload.mobile_number)
        login_channel = channel or payload.login_channel
        otp_purpose = purpose or f"{login_channel.value}_LOGIN"
        await self._precheck_otp_request(normalized_mobile, login_channel, otp_purpose)
        otp = self._development_or_random_otp()
        await self._enforce_request_rate_limit(normalized_mobile, otp_purpose, login_channel)
        await self._invalidate_active_challenges(normalized_mobile, otp_purpose, login_channel)
        challenge = await self.otp_service.store_hashed_otp(
            payload=payload,
            mobile_number=normalized_mobile,
            purpose=otp_purpose,
            login_channel=login_channel,
            otp=otp,
        )
        await self.otp_provider.send_otp(
            mobile_number=normalized_mobile,
            country_code=payload.country_code,
            message="Your MBGA login OTP has been generated.",
        )
        await self.repository.session.commit()
        return OTPRequestResponse(
            request_id=challenge.id,
            expires_in=self.settings.otp_expiry_seconds,
            resend_after=self.settings.otp_resend_cooldown_seconds,
        )

    async def verify_otp(
        self,
        payload: OTPVerifyRequest,
        *,
        purpose: str,
        channel: LoginChannel,
    ) -> OTPVerifyResponse:
        now = datetime.now(UTC)
        result = await self.repository.session.execute(
            select(OtpChallenge).where(OtpChallenge.id == payload.request_id).with_for_update()
        )
        challenge = result.scalar_one_or_none()
        if challenge is None or challenge.purpose != purpose:
            raise self._safe_error("OTP_PURPOSE_MISMATCH", status.HTTP_400_BAD_REQUEST)
        if challenge.login_channel != channel.value:
            raise self._safe_error("CHANNEL_NOT_ALLOWED", status.HTTP_403_FORBIDDEN)
        if challenge.consumed_at is not None:
            raise self._safe_error("OTP_ALREADY_USED", status.HTTP_400_BAD_REQUEST)
        expires_at = challenge.expires_at if challenge.expires_at.tzinfo else challenge.expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            raise self._safe_error("OTP_EXPIRED", status.HTTP_400_BAD_REQUEST)
        if challenge.attempts >= challenge.max_attempts:
            raise self._safe_error("OTP_ATTEMPTS_EXCEEDED", status.HTTP_400_BAD_REQUEST)
        if not verify_secret(payload.otp, challenge.otp_hash):
            challenge.attempts += 1
            await self.repository.session.commit()
            raise self._safe_error("OTP_INVALID", status.HTTP_400_BAD_REQUEST)
        challenge.consumed_at = now
        user, permissions, active_roles, profile = await self._validate_account(challenge.mobile_number, channel, purpose)
        if purpose == "CUSTOMER_REGISTRATION":
            token = await self._issue_token_pair(user, channel, payload.device.device_id if payload.device else None, token_scope="onboarding")
        else:
            token = await self._issue_token_pair(user, channel, payload.device.device_id if payload.device else None)
        await self.repository.session.commit()
        return OTPVerifyResponse(
            token=token,
            user_id=user.id,
            login_channel=channel,
            is_new_user=False,
            code="OTP_VERIFIED",
            message="OTP verified",
        )

    async def refresh_token(self, payload: RefreshTokenRequest, *, channel: LoginChannel) -> TokenPair:
        try:
            decoded = jwt.decode(payload.refresh_token, self.settings.jwt_signing_secret, algorithms=[self.settings.jwt_algorithm])
        except Exception as exc:
            raise self._safe_error("SESSION_EXPIRED", status.HTTP_401_UNAUTHORIZED) from exc
        if decoded.get("token_type") != "refresh" or decoded.get("login_channel") != channel.value:
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        session = await self.repository.session.get(LoginSession, decoded.get("session_id"))
        if session is None or session.revoked_at is not None:
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        if not self._verify_refresh_token(payload.refresh_token, session.refresh_token_hash):
            session.revoked_at = datetime.now(UTC)
            await self.repository.session.commit()
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        user = await self.repository.session.get(User, session.user_id)
        if user is None:
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        await self._validate_account(user.mobile_number or "", channel, f"{channel.value}_LOGIN")
        session.revoked_at = datetime.now(UTC)
        token_pair = await self._issue_token_pair(user, channel, payload.device_id)
        await self.repository.session.commit()
        return token_pair

    async def logout(self, payload: LogoutRequest) -> None:
        if not payload.refresh_token:
            return
        try:
            decoded = jwt.decode(payload.refresh_token, self.settings.jwt_signing_secret, algorithms=[self.settings.jwt_algorithm])
        except Exception:
            return
        session = await self.repository.session.get(LoginSession, decoded.get("session_id"))
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            await self.repository.session.commit()

    async def logout_all(self, user_id: str) -> None:
        await self.repository.session.execute(
            update(LoginSession).where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC))
        )
        await self.repository.session.commit()

    async def me(self, access_token: str, *, channel: LoginChannel) -> CurrentUserResponse:
        try:
            decoded = jwt.decode(access_token, self.settings.jwt_signing_secret, algorithms=[self.settings.jwt_algorithm])
        except Exception as exc:
            raise self._safe_error("SESSION_EXPIRED", status.HTTP_401_UNAUTHORIZED) from exc
        if decoded.get("token_type") not in {"access", "onboarding"} or decoded.get("login_channel") != channel.value:
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        user = await self.repository.session.get(User, decoded.get("sub"))
        if user is None:
            raise self._safe_error("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        permissions = await UserRoleRepository(self.repository.session).get_effective_permissions(
            user_id=user.id,
            login_channel=channel,
            now=datetime.now(UTC),
        )
        roles = await self._active_role_codes(user.id)
        return CurrentUserResponse(
            user_id=user.id,
            display_name=user.full_name or user.username or user.mobile_number,
            mobile_number=user.mobile_number,
            country_code=user.country_code,
            role=None,
            active_roles=roles,
            effective_permissions=sorted(permissions),
            login_channel=channel,
            status=user.status,
        )

    def _development_or_random_otp(self) -> str:
        if self.settings.dev_fixed_otp_enabled:
            if not self.settings.dev_fixed_otp_code:
                raise RuntimeError("Fixed OTP is enabled but DEV_FIXED_OTP_CODE is missing")
            return self.settings.dev_fixed_otp_code
        return self.otp_service.generate_otp()

    async def _precheck_otp_request(self, mobile: str, channel: LoginChannel, purpose: str) -> None:
        if purpose == "CUSTOMER_REGISTRATION":
            return
        if channel == LoginChannel.CUSTOMER:
            profile = await self.repository.session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))
            if profile is None:
                raise self._safe_error("NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)
            return
        user = await self._find_user_by_mobile(mobile)
        if user is None:
            raise self._safe_error("NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)

    async def _enforce_request_rate_limit(self, mobile: str, purpose: str, channel: LoginChannel) -> None:
        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        count = len(
            (
                await self.repository.session.execute(
                    select(OtpChallenge.id).where(
                        OtpChallenge.mobile_number == mobile,
                        OtpChallenge.purpose == purpose,
                        OtpChallenge.login_channel == channel.value,
                        OtpChallenge.created_at >= one_hour_ago,
                    )
                )
            ).all()
        )
        if count >= self.settings.otp_max_requests_per_hour:
            raise self._safe_error("OTP_RATE_LIMITED", status.HTTP_429_TOO_MANY_REQUESTS)

    async def _invalidate_active_challenges(self, mobile: str, purpose: str, channel: LoginChannel) -> None:
        now = datetime.now(UTC)
        await self.repository.session.execute(
            update(OtpChallenge)
            .where(
                OtpChallenge.mobile_number == mobile,
                OtpChallenge.purpose == purpose,
                OtpChallenge.login_channel == channel.value,
                OtpChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )

    async def _validate_account(self, mobile: str, channel: LoginChannel, purpose: str):
        if purpose == "CUSTOMER_REGISTRATION":
            user = await self._find_or_create_onboarding_user(mobile)
            return user, set(), [], None
        user = await self._find_user_by_mobile(mobile)
        if user is None:
            raise self._safe_error("NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)
        if user.status == "BLOCKED":
            raise self._safe_error("ACCOUNT_BLOCKED", status.HTTP_403_FORBIDDEN)
        if user.status != "ACTIVE":
            raise self._safe_error("ACCOUNT_INACTIVE", status.HTTP_403_FORBIDDEN)
        permissions = await UserRoleRepository(self.repository.session).get_effective_permissions(
            user_id=user.id,
            login_channel=channel,
            now=datetime.now(UTC),
        )
        roles = await self._active_role_codes(user.id)
        if not permissions:
            raise self._safe_error("ROLE_NOT_ASSIGNED", status.HTTP_403_FORBIDDEN)
        if channel == LoginChannel.ADMIN and "dashboard.view" not in permissions:
            raise self._safe_error("PERMISSION_DENIED", status.HTTP_403_FORBIDDEN)
        if channel == LoginChannel.MERCHANT:
            merchant_ok = await self._merchant_allowed(user.id)
            if not merchant_ok:
                raise self._safe_error("ACCOUNT_PENDING_APPROVAL", status.HTTP_403_FORBIDDEN)
        if channel == LoginChannel.DELIVERY:
            delivery_ok = await self._delivery_allowed(user.id)
            if not delivery_ok:
                raise self._safe_error("ACCOUNT_PENDING_APPROVAL", status.HTTP_403_FORBIDDEN)
        if channel == LoginChannel.CUSTOMER:
            await self._customer_full_login_allowed(user.id, mobile)
        return user, permissions, roles, None

    async def _find_user_by_mobile(self, mobile: str) -> User | None:
        return await self.repository.session.scalar(select(User).where(User.mobile_number == mobile))

    async def _find_or_create_onboarding_user(self, mobile: str) -> User:
        user = await self._find_user_by_mobile(mobile)
        if user:
            return user
        now = datetime.now(UTC)
        user = User(
            id=str(uuid4()),
            mobile_number=mobile,
            country_code="+91",
            role="customer",
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self.repository.session.add(user)
        await self.repository.session.flush()
        return user

    async def _active_role_codes(self, user_id: str) -> list[str]:
        now = datetime.now(UTC)
        result = await self.repository.session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, UserRole.is_active.is_(True))
            .where((UserRole.valid_from.is_(None)) | (UserRole.valid_from <= now))
            .where((UserRole.valid_until.is_(None)) | (UserRole.valid_until > now))
            .where(Role.is_active.is_(True))
            .order_by(Role.code)
        )
        return list(result.scalars().all())

    async def _merchant_allowed(self, user_id: str) -> bool:
        result = await self.repository.session.execute(
            select(Merchant)
            .join(MerchantUser, MerchantUser.merchant_id == Merchant.id)
            .where(MerchantUser.user_id == user_id, Merchant.status == "ACTIVE", Merchant.approval_status == "APPROVED", MerchantUser.status == "ACTIVE")
        )
        return result.scalar_one_or_none() is not None

    async def _delivery_allowed(self, user_id: str) -> bool:
        profile = await self.repository.session.scalar(
            select(DeliveryProfile).where(
                DeliveryProfile.user_id == user_id,
                DeliveryProfile.status == "ACTIVE",
                DeliveryProfile.approval_status == "APPROVED",
            )
        )
        return profile is not None

    async def _customer_full_login_allowed(self, user_id: str, mobile: str) -> None:
        profile = await self.repository.session.scalar(select(CustomerProfile).where(CustomerProfile.mobile_number == mobile))
        if profile is None:
            raise self._safe_error("NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)
        if profile.status == "REJECTED":
            raise self._safe_error("ACCOUNT_REJECTED", status.HTTP_403_FORBIDDEN)
        if profile.status == "SUSPENDED":
            raise self._safe_error("ACCOUNT_SUSPENDED", status.HTTP_403_FORBIDDEN)
        if profile.status != "APPROVED":
            raise self._safe_error("ACCOUNT_PENDING_APPROVAL", status.HTTP_403_FORBIDDEN)
        pending_docs = await self.repository.session.scalar(
            select(CustomerDocument).where(CustomerDocument.customer_id == profile.id, CustomerDocument.is_mandatory.is_(True), CustomerDocument.status != "APPROVED")
        )
        if pending_docs is not None:
            raise self._safe_error("DOCUMENTS_PENDING_APPROVAL", status.HTTP_403_FORBIDDEN)

    async def _issue_token_pair(self, user: User, channel: LoginChannel, device_id: str | None, token_scope: str = "access") -> TokenPair:
        now = datetime.now(UTC)
        session_id = str(uuid4())
        access_exp = now + timedelta(minutes=self.settings.access_token_expires_minutes)
        refresh_exp = now + timedelta(days=self.settings.refresh_token_expires_days)
        access_payload = {
            "sub": user.id,
            "session_id": session_id,
            "token_type": token_scope,
            "login_channel": channel.value,
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": access_exp,
        }
        refresh_token = secrets.token_urlsafe(48)
        refresh_payload = {
            "sub": user.id,
            "session_id": session_id,
            "token_type": "refresh",
            "login_channel": channel.value,
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": refresh_exp,
            "secret": refresh_token,
        }
        access_token = jwt.encode(access_payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)
        encoded_refresh = jwt.encode(refresh_payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)
        self.repository.session.add(
            LoginSession(
                id=session_id,
                user_id=user.id,
                refresh_token_hash=self._hash_refresh_token(encoded_refresh),
                device_id=device_id,
                created_at=now,
                expires_at=refresh_exp,
                last_activity_at=now,
                revoked_at=None,
            )
        )
        return TokenPair(access_token=access_token, refresh_token=encoded_refresh, expires_in=self.settings.access_token_expires_minutes * 60)

    def _safe_error(self, code: str, http_status: int) -> HTTPException:
        return HTTPException(status_code=http_status, detail={"code": code, "message": code.replace("_", " ").title()})

    def _hash_refresh_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _verify_refresh_token(self, token: str, hashed: str) -> bool:
        return hmac.compare_digest(self._hash_refresh_token(token), hashed)
