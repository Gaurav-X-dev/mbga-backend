import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import uuid4

import jwt
from fastapi import status
from sqlalchemy import case, func, or_, select, update

from app.config.app import Settings
from app.modules.authentication.account_state import AccountState, AccountStateResolver
from app.modules.authentication.audit import AuthAuditor, ClientInfo
from app.modules.authentication.constants import (
    REFRESH_TOKEN_TYPE,
    AuthEventType,
    LoginChannel,
    SessionType,
)
from app.modules.authentication.mobile_number import (
    ensure_india_country_code,
    normalize_mobile_number,
)
from app.modules.authentication.models import LoginSession
from app.modules.authentication.otp_models import OtpChallenge
from app.modules.authentication.otp_service import OTPService
from app.modules.authentication.password_hasher import verify_secret
from app.modules.authentication.repository import AuthenticationRepository
from app.modules.authentication.schemas import (
    CurrentUserResponse,
    CustomerProfileSummary,
    DeliveryProfileSummary,
    DeviceInfo,
    LogoutRequest,
    MerchantSummary,
    OTPRequest,
    OTPRequestResponse,
    OTPResendRequest,
    OTPVerifyRequest,
    OTPVerifyResponse,
    RefreshTokenRequest,
    TokenPair,
    user_type_for_channel,
)
from app.modules.authentication.session_service import SessionService, utc_naive, utc_now_naive
from app.modules.authentication.throttle import WINDOW, RequestThrottle
from app.modules.users.models import User
from app.shared.exceptions.api_error import ApiError
from app.shared.otp.provider import OTPDeliveryError, OTPDeliveryProvider

REGISTRATION_PURPOSE = "CUSTOMER_REGISTRATION"
FULL_SESSION = frozenset({SessionType.ACCESS.value})
ONBOARDING_SESSION = frozenset({SessionType.ONBOARDING.value})


def session_types_for_purpose(purpose: str) -> frozenset[str]:
    return ONBOARDING_SESSION if purpose == REGISTRATION_PURPOSE else FULL_SESSION


def _pick(device: DeviceInfo | None, field: str, previous: LoginSession | None, previous_field: str | None = None) -> str | None:
    """A device value sent with this request, otherwise the value of the session being rotated."""
    value = getattr(device, field, None) if device else None
    if value:
        return value
    return getattr(previous, previous_field or field, None) if previous else None


class AuthenticationService:
    def __init__(
        self,
        repository: AuthenticationRepository,
        otp_service: OTPService,
        otp_provider: OTPDeliveryProvider,
        settings: Settings,
        client: ClientInfo | None = None,
    ) -> None:
        self.repository = repository
        self.otp_service = otp_service
        self.otp_provider = otp_provider
        self.settings = settings
        self.client = client or ClientInfo()

    @property
    def db(self):
        return self.repository.session

    @property
    def audit(self) -> AuthAuditor:
        return AuthAuditor(self.db, store_ip=self.settings.auth_audit_store_ip)

    @property
    def throttle(self) -> RequestThrottle:
        return RequestThrottle(self.db, self.settings.jwt_signing_secret)

    # ------------------------------------------------------------------ OTP

    async def request_otp(self, payload: OTPRequest, *, purpose: str | None = None, channel: LoginChannel | None = None) -> OTPRequestResponse:
        """Accept a code request and send a code.

        A number with no account that may sign in on this channel is refused directly, so the response
        does tell a caller whether a number is registered. Rate limits are the only guard against
        using that to enumerate accounts.
        """
        ensure_india_country_code(payload.country_code)
        mobile = normalize_mobile_number(payload.mobile_number)
        login_channel = channel or payload.login_channel
        otp_purpose = purpose or f"{login_channel.value}_LOGIN"
        device_id = payload.device.device_id if payload.device else None
        async with self._audited_rejection(AuthEventType.OTP_REQUEST_REJECTED, login_channel, mobile, device_id):
            await self.throttle.hit("otp_request:ip", self.client.ip_address, self.settings.otp_request_limit_per_ip, code="OTP_RATE_LIMITED")
            await self.throttle.hit("otp_request:device", device_id, self.settings.otp_request_limit_per_device, code="OTP_RATE_LIMITED")
            await self._enforce_failed_attempt_lockout(mobile, otp_purpose, login_channel)
            await self._enforce_request_rate_limit(mobile, otp_purpose, login_channel)
        user, denial = await self._code_eligibility(mobile, login_channel, otp_purpose)
        if denial is not None:
            await self._reject_code_request(AuthEventType.OTP_REQUEST_REJECTED, login_channel, user, mobile, device_id, denial)
        await self._invalidate_active_challenges(mobile, otp_purpose, login_channel)
        challenge, otp = await self._create_challenge(payload, mobile, otp_purpose, login_channel)
        await self.audit.record(
            AuthEventType.OTP_REQUESTED,
            channel=login_channel,
            success=True,
            user_id=user.id if user else None,
            mobile_number=mobile,
            device_id=device_id,
            client=self.client,
            reason="CODE_SENT",
        )
        await self.db.commit()
        return self._request_response(challenge, otp)

    async def resend_otp(self, payload: OTPResendRequest, *, purpose: str, channel: LoginChannel) -> OTPRequestResponse:
        now = utc_now_naive()
        device_id = payload.device.device_id if payload.device else None
        async with self._audited_rejection(AuthEventType.OTP_REQUEST_REJECTED, channel, None, device_id):
            await self.throttle.hit("otp_request:ip", self.client.ip_address, self.settings.otp_request_limit_per_ip, code="OTP_RATE_LIMITED")
            previous = await self._lock_challenge(payload.request_id, purpose, channel)
            if previous.consumed_at is not None:
                raise ApiError("OTP_ALREADY_USED", status.HTTP_400_BAD_REQUEST)
            if previous.resend_available_at and utc_naive(previous.resend_available_at) > now:
                wait = max(1, ceil((utc_naive(previous.resend_available_at) - now).total_seconds()))
                raise ApiError("OTP_RESEND_TOO_SOON", status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": str(wait)})
            await self.throttle.hit("otp_request:device", device_id, self.settings.otp_request_limit_per_device, code="OTP_RATE_LIMITED")
            await self._enforce_failed_attempt_lockout(previous.mobile_number, purpose, channel)
            await self._enforce_request_rate_limit(previous.mobile_number, purpose, channel)
        previous.consumed_at = now
        # Eligibility is checked again: the account may have changed since the first request.
        user, denial = await self._code_eligibility(previous.mobile_number, channel, purpose)
        if denial is not None:
            await self._reject_code_request(AuthEventType.OTP_REQUEST_REJECTED, channel, user, previous.mobile_number, device_id, denial)
        challenge, otp = await self._create_challenge(payload, previous.mobile_number, purpose, channel)
        await self.audit.record(
            AuthEventType.OTP_RESEND_REQUESTED,
            channel=channel,
            success=True,
            user_id=user.id if user else None,
            mobile_number=previous.mobile_number,
            device_id=device_id,
            client=self.client,
            reason="CODE_SENT",
        )
        await self.db.commit()
        return self._request_response(challenge, otp)

    async def verify_otp(self, payload: OTPVerifyRequest, *, purpose: str, channel: LoginChannel) -> OTPVerifyResponse:
        now = utc_now_naive()
        device_id = payload.device.device_id if payload.device else None
        if len(payload.otp) != self.settings.otp_length:
            message = f"Enter the {self.settings.otp_length}-digit code."
            raise ApiError("VALIDATION_ERROR", status.HTTP_422_UNPROCESSABLE_CONTENT, fields=[{"field": "otp", "code": "otp_length", "message": message}])
        async with self._audited_rejection(AuthEventType.OTP_VERIFICATION_FAILED, channel, None, device_id):
            await self.throttle.hit("otp_verify:ip", self.client.ip_address, self.settings.otp_verify_limit_per_ip)
            challenge = await self._lock_challenge(payload.request_id, purpose, channel)
            if challenge.consumed_at is not None:
                raise ApiError("OTP_ALREADY_USED", status.HTTP_400_BAD_REQUEST)
            if utc_naive(challenge.expires_at) <= now:
                raise ApiError("OTP_EXPIRED", status.HTTP_400_BAD_REQUEST)
            if challenge.attempts >= challenge.max_attempts:
                raise ApiError("OTP_ATTEMPTS_EXCEEDED", status.HTTP_400_BAD_REQUEST)
            await self._enforce_failed_attempt_lockout(challenge.mobile_number, purpose, channel)
        if challenge.dispatch_suppressed or not verify_secret(payload.otp, challenge.otp_hash):
            challenge.attempts += 1
            await self.audit.record(
                AuthEventType.OTP_VERIFICATION_FAILED,
                channel=channel,
                success=False,
                mobile_number=challenge.mobile_number,
                device_id=device_id,
                client=self.client,
                reason="OTP_INVALID",
            )
            await self.db.commit()
            raise ApiError("OTP_INVALID", status.HTTP_400_BAD_REQUEST)
        challenge.consumed_at = now
        await self.audit.record(
            AuthEventType.OTP_VERIFICATION_SUCCEEDED,
            channel=channel,
            success=True,
            mobile_number=challenge.mobile_number,
            device_id=device_id,
            client=self.client,
        )
        if purpose == REGISTRATION_PURPOSE:
            user, is_new_user = await self._find_or_create_onboarding_user(challenge.mobile_number)
            session_type = SessionType.ONBOARDING
        else:
            user, is_new_user = await self._find_user_by_mobile(challenge.mobile_number), False
            session_type = SessionType.ACCESS
            if user is None:
                await self._reject_login(channel, None, challenge.mobile_number, device_id, "NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)
        state = await AccountStateResolver(self.db).resolve(user, channel)
        denial = state.onboarding_denial if session_type == SessionType.ONBOARDING else state.denial
        if denial is not None:
            # The code stays consumed so it cannot be replayed.
            await self._reject_login(channel, user.id, challenge.mobile_number, device_id, *denial)
        token = await self._issue_token_pair(user, channel, device_id, session_type=session_type, device=payload.device)
        await self.audit.record(
            AuthEventType.LOGIN_SUCCEEDED,
            channel=channel,
            success=True,
            user_id=user.id,
            mobile_number=challenge.mobile_number,
            device_id=device_id,
            client=self.client,
            reason=session_type.value.upper(),
        )
        await self.db.commit()
        return OTPVerifyResponse(
            token=token,
            is_new_user=is_new_user,
            session_type=session_type.value,
            **self._account_fields(state, session_type.value),
        )

    # ------------------------------------------------------------------ sessions

    async def refresh_token(
        self,
        payload: RefreshTokenRequest,
        *,
        channel: LoginChannel,
        session_types: frozenset[str] = FULL_SESSION,
    ) -> TokenPair:
        try:
            decoded = jwt.decode(payload.refresh_token, self.settings.jwt_signing_secret, algorithms=[self.settings.jwt_algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise ApiError("SESSION_EXPIRED", status.HTTP_401_UNAUTHORIZED) from exc
        except jwt.InvalidTokenError as exc:
            raise ApiError("TOKEN_INVALID", status.HTTP_401_UNAUTHORIZED) from exc
        if decoded.get("token_type") != REFRESH_TOKEN_TYPE:
            raise ApiError("TOKEN_TYPE_NOT_ALLOWED", status.HTTP_401_UNAUTHORIZED)
        if decoded.get("login_channel") != channel.value:
            raise ApiError("TOKEN_CHANNEL_MISMATCH", status.HTTP_401_UNAUTHORIZED)
        # The row lock serialises concurrent refreshes of the same session.
        result = await self.db.execute(select(LoginSession).where(LoginSession.id == decoded.get("session_id")).with_for_update())
        session = result.scalar_one_or_none()
        if session is None or session.user_id != decoded.get("sub"):
            raise ApiError("SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)
        session_type = session.session_type or decoded.get("session_type") or SessionType.ACCESS.value
        if session_type not in session_types:
            raise ApiError("TOKEN_TYPE_NOT_ALLOWED", status.HTTP_401_UNAUTHORIZED)
        sessions = SessionService(self.db, self.settings)
        if not self._verify_refresh_token(payload.refresh_token, session.refresh_token_hash):
            await sessions.revoke(session, "REFRESH_TOKEN_MISMATCH")
            await self._reject_refresh(session, channel, "REFRESH_TOKEN_MISMATCH", status.HTTP_401_UNAUTHORIZED, code="SESSION_REVOKED")
        if session.revoked_at is not None:
            await self._handle_revoked_refresh(session, channel)
        if session.expires_at is not None and utc_naive(session.expires_at) <= utc_now_naive():
            await self._reject_refresh(session, channel, "SESSION_EXPIRED", status.HTTP_401_UNAUTHORIZED)
        user = await self.db.get(User, session.user_id)
        if user is None:
            await self._reject_refresh(session, channel, "USER_NOT_FOUND", status.HTTP_401_UNAUTHORIZED, code="SESSION_REVOKED")
        state = await AccountStateResolver(self.db).resolve(user, channel)
        denial = state.onboarding_denial if session_type == SessionType.ONBOARDING.value else state.denial
        if denial is not None:
            await self._reject_refresh(session, channel, denial[0], denial[1])
        device = payload.device
        device_id = (device.device_id if device and device.device_id else None) or payload.device_id or session.device_id
        token_pair = await self._issue_token_pair(
            user,
            channel,
            device_id,
            session_type=SessionType(session_type),
            family_id=session.family_id or session.id,
            device=device,
            previous=session,
        )
        # Revoke after copying the device details: revoking clears the old session's push token.
        session.rotated_at = datetime.now(UTC)
        await sessions.revoke(session, "ROTATED")
        await self.audit.record(AuthEventType.TOKEN_REFRESHED, channel=channel, success=True, user_id=user.id, device_id=device_id, client=self.client)
        await self.db.commit()
        return token_pair

    async def _handle_revoked_refresh(self, session: LoginSession, channel: LoginChannel) -> None:
        """A revoked refresh token was presented. If it was rotated earlier, someone replayed an old token."""
        rotated_at = utc_naive(session.rotated_at)
        grace = timedelta(seconds=self.settings.refresh_reuse_grace_seconds)
        if rotated_at is not None and rotated_at + grace < utc_now_naive():
            family_id = session.family_id or session.id
            result = await self.db.execute(
                update(LoginSession)
                .where(or_(LoginSession.family_id == family_id, LoginSession.id == family_id), LoginSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC), revoked_reason="REFRESH_TOKEN_REUSED", push_token=None)
            )
            await self.audit.record(
                AuthEventType.REFRESH_TOKEN_REUSE_DETECTED,
                channel=channel,
                success=False,
                user_id=session.user_id,
                device_id=session.device_id,
                client=self.client,
                reason=f"REVOKED_{result.rowcount or 0}_SESSIONS",
                entity_id=family_id,
            )
        await self._reject_refresh(session, channel, "SESSION_REVOKED", status.HTTP_401_UNAUTHORIZED)

    async def _reject_refresh(self, session: LoginSession, channel: LoginChannel, reason: str, http_status: int, *, code: str | None = None) -> None:
        await self.audit.record(
            AuthEventType.TOKEN_REFRESH_REJECTED,
            channel=channel,
            success=False,
            user_id=session.user_id,
            device_id=session.device_id,
            client=self.client,
            reason=reason,
        )
        if reason in {"ACCOUNT_BLOCKED", "MERCHANT_BLOCKED"}:
            await self.audit.record(AuthEventType.BLOCKED_ACCOUNT_ACCESS, channel=channel, success=False, user_id=session.user_id, client=self.client, reason=reason)
        await self.db.commit()
        raise ApiError(code or reason, http_status)

    async def logout(self, payload: LogoutRequest, *, channel: LoginChannel | None = None) -> None:
        """Revoke the session behind a refresh token.

        Always succeeds (204) so that a sign-out can never get stuck on the device: a missing, unreadable,
        already-revoked or other-app token simply revokes nothing.
        """
        if not payload.refresh_token:
            return
        try:
            decoded = jwt.decode(payload.refresh_token, self.settings.jwt_signing_secret, algorithms=[self.settings.jwt_algorithm])
        except jwt.InvalidTokenError:
            return
        if decoded.get("token_type") != REFRESH_TOKEN_TYPE or (channel is not None and decoded.get("login_channel") != channel.value):
            return
        session = await self.db.get(LoginSession, decoded.get("session_id"))
        if session is None or not self._verify_refresh_token(payload.refresh_token, session.refresh_token_hash):
            return
        if session.revoked_at is None:
            await SessionService(self.db, self.settings).revoke(session, "LOGOUT")
            await self.audit.record(AuthEventType.LOGOUT, channel=channel, success=True, user_id=session.user_id, device_id=session.device_id, client=self.client)
            await self.db.commit()

    async def logout_all(self, access_token: str | None, *, channel: LoginChannel, session_types: frozenset[str] = FULL_SESSION) -> None:
        sessions = SessionService(self.db, self.settings)
        validated = await sessions.validate_access_token(access_token, allowed_types=session_types, channel=channel)
        revoked = await sessions.revoke_all_for_user(validated.user.id, "LOGOUT_ALL")
        await self.audit.record(
            AuthEventType.LOGOUT_ALL,
            channel=channel,
            success=True,
            user_id=validated.user.id,
            client=self.client,
            reason=f"REVOKED_{revoked}_SESSIONS",
        )
        await self.db.commit()

    async def me(self, access_token: str | None, *, channel: LoginChannel, session_types: frozenset[str] = FULL_SESSION) -> CurrentUserResponse:
        validated = await SessionService(self.db, self.settings).validate_access_token(
            access_token,
            allowed_types=session_types,
            channel=channel,
        )
        user = validated.user
        fields = self._account_fields(validated.state, validated.token_type)
        return CurrentUserResponse(
            display_name=user.full_name or user.username or user.mobile_number,
            mobile_number=user.mobile_number,
            country_code=user.country_code,
            effective_permissions=sorted(validated.state.permissions),
            status=user.status,
            session_type=validated.token_type,
            profile=fields["delivery_profile"] or fields["customer_profile"],
            **fields,
        )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _account_fields(state: AccountState, session_type: str) -> dict:
        return {
            "user_id": state.user.id,
            "login_channel": state.channel,
            "user_type": user_type_for_channel(state.channel),
            "role": state.role,
            "active_roles": state.active_roles,
            "account_status": state.account_status,
            "approval_status": state.approval_status,
            "profile_completion_status": state.profile_completion_status,
            "next_action": state.next_action_for(session_type),
            "merchant": MerchantSummary(**state.merchant) if state.merchant else None,
            "delivery_profile": DeliveryProfileSummary(**state.delivery_profile) if state.delivery_profile else None,
            "customer_profile": CustomerProfileSummary(**state.customer_profile) if state.customer_profile else None,
        }

    def _request_response(self, challenge: OtpChallenge, otp: str) -> OTPRequestResponse:
        dev_otp = otp if self.settings.dev_expose_otp_in_response else None
        message = f"OTP request accepted. OTP: {otp}" if dev_otp else "OTP request accepted"
        return OTPRequestResponse(
            request_id=challenge.id,
            message=message,
            expires_in=self.settings.otp_expiry_seconds,
            resend_after=self.settings.otp_resend_cooldown_seconds,
            # Settings validation guarantees this is off outside local/development/test.
            dev_otp=dev_otp,
        )

    def _audited_rejection(self, event: AuthEventType, channel: LoginChannel, mobile: str | None, device_id: str | None):
        service = self

        class _Guard:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                if isinstance(exc, ApiError):
                    await service.audit.record(
                        event,
                        channel=channel,
                        success=False,
                        mobile_number=mobile,
                        device_id=device_id,
                        client=service.client,
                        reason=exc.code,
                    )
                    # Keep the counted attempt and the audit record even though the request fails.
                    await service.db.commit()
                return False

        return _Guard()

    async def _reject_login(self, channel: LoginChannel, user_id: str | None, mobile: str, device_id: str | None, code: str, http_status: int) -> None:
        await self.audit.record(
            AuthEventType.LOGIN_REJECTED,
            channel=channel,
            success=False,
            user_id=user_id,
            mobile_number=mobile,
            device_id=device_id,
            client=self.client,
            reason=code,
        )
        if code in {"ACCOUNT_BLOCKED", "MERCHANT_BLOCKED"}:
            await self.audit.record(AuthEventType.BLOCKED_ACCOUNT_ACCESS, channel=channel, success=False, user_id=user_id, mobile_number=mobile, client=self.client, reason=code)
        await self.db.commit()
        raise ApiError(code, http_status)

    async def _code_eligibility(self, mobile: str, channel: LoginChannel, purpose: str) -> tuple[User | None, tuple[str, int] | None]:
        """Return the account and, when no code may be sent, the (error code, HTTP status) to raise."""
        user = await self._find_user_by_mobile(mobile)
        if purpose == REGISTRATION_PURPOSE:
            if user is not None and user.status == "BLOCKED":
                return user, ("ACCOUNT_BLOCKED", status.HTTP_403_FORBIDDEN)
            return user, None
        if user is None:
            return None, ("NUMBER_NOT_REGISTERED", status.HTTP_404_NOT_FOUND)
        state = await AccountStateResolver(self.db).resolve(user, channel)
        return user, state.denial

    async def _reject_code_request(
        self,
        event: AuthEventType,
        channel: LoginChannel,
        user: User | None,
        mobile: str,
        device_id: str | None,
        denial: tuple[str, int],
    ) -> None:
        """Refuse an OTP request outright. No challenge row is created and no code is sent."""
        code, http_status = denial
        await self.audit.record(
            event,
            channel=channel,
            success=False,
            user_id=user.id if user else None,
            mobile_number=mobile,
            device_id=device_id,
            client=self.client,
            reason=code,
        )
        if code in {"ACCOUNT_BLOCKED", "MERCHANT_BLOCKED"}:
            await self.audit.record(
                AuthEventType.BLOCKED_ACCOUNT_ACCESS,
                channel=channel,
                success=False,
                user_id=user.id if user else None,
                mobile_number=mobile,
                client=self.client,
                reason=code,
            )
        await self.db.commit()
        raise ApiError(code, http_status)

    async def _create_challenge(self, payload, mobile: str, purpose: str, channel: LoginChannel) -> tuple[OtpChallenge, str]:
        """Create and dispatch a challenge, returning it with the plaintext code.

        The plaintext is only ever handed back to the caller so that `_request_response` can echo it
        under DEV_EXPOSE_OTP_IN_RESPONSE. It is never stored: the row keeps only the hash.
        """
        otp = self._development_or_random_otp()
        challenge = await self.otp_service.store_hashed_otp(
            payload=payload,
            mobile_number=mobile,
            purpose=purpose,
            login_channel=channel,
            otp=otp,
            ip_address=self.client.ip_address,
        )
        challenge.dispatch_suppressed = False
        try:
            result = await self.otp_provider.send_otp(
                mobile_number=mobile,
                otp=otp,
                purpose=purpose,
                expires_in_seconds=self.settings.otp_expiry_seconds,
            )
        except OTPDeliveryError as exc:
            await self.db.rollback()
            await self.audit.record(
                AuthEventType.OTP_REQUEST_REJECTED,
                channel=channel,
                success=False,
                mobile_number=mobile,
                client=self.client,
                reason=f"OTP_DELIVERY_FAILED:{exc.reason}"[:60],
            )
            await self.db.commit()
            raise ApiError("OTP_DELIVERY_FAILED", status.HTTP_503_SERVICE_UNAVAILABLE, headers={"Retry-After": "30"}) from exc
        challenge.delivery_status = "SENT"
        challenge.delivery_provider = result.provider
        challenge.delivery_reference = result.reference
        return challenge, otp

    async def _lock_challenge(self, request_id: str, purpose: str, channel: LoginChannel) -> OtpChallenge:
        result = await self.db.execute(select(OtpChallenge).where(OtpChallenge.id == request_id).with_for_update())
        challenge = result.scalar_one_or_none()
        if challenge is None or challenge.purpose != purpose:
            raise ApiError("OTP_PURPOSE_MISMATCH", status.HTTP_400_BAD_REQUEST)
        if challenge.login_channel != channel.value:
            raise ApiError("CHANNEL_NOT_ALLOWED", status.HTTP_403_FORBIDDEN)
        return challenge

    def _development_or_random_otp(self) -> str:
        if self.settings.dev_fixed_otp_enabled:
            if not self.settings.dev_fixed_otp_code:
                raise RuntimeError("Fixed OTP is enabled but DEV_FIXED_OTP_CODE is missing")
            return self.settings.dev_fixed_otp_code
        return self.otp_service.generate_otp()

    def _challenge_window_filter(self, mobile: str, purpose: str, channel: LoginChannel):
        return (
            OtpChallenge.mobile_number == mobile,
            OtpChallenge.purpose == purpose,
            OtpChallenge.login_channel == channel.value,
            OtpChallenge.created_at >= utc_now_naive() - WINDOW,
        )

    async def _enforce_request_rate_limit(self, mobile: str, purpose: str, channel: LoginChannel) -> None:
        count, oldest = (
            await self.db.execute(
                select(func.count(OtpChallenge.id), func.min(OtpChallenge.created_at)).where(*self._challenge_window_filter(mobile, purpose, channel))
            )
        ).one()
        if count >= self.settings.otp_max_requests_per_hour:
            raise ApiError("OTP_RATE_LIMITED", status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": self._retry_after(oldest)})

    async def _enforce_failed_attempt_lockout(self, mobile: str, purpose: str, channel: LoginChannel) -> None:
        failed, oldest = (
            await self.db.execute(
                select(func.coalesce(func.sum(OtpChallenge.attempts), 0), func.min(OtpChallenge.created_at)).where(
                    *self._challenge_window_filter(mobile, purpose, channel),
                    OtpChallenge.attempts > 0,
                )
            )
        ).one()
        if int(failed) >= self.settings.otp_max_failed_attempts_per_hour:
            raise ApiError("OTP_LOCKED", status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": self._retry_after(oldest)})

    @staticmethod
    def _retry_after(oldest: datetime | None) -> str:
        if oldest is None:
            return str(int(WINDOW.total_seconds()))
        return str(max(1, ceil((utc_naive(oldest) + WINDOW - utc_now_naive()).total_seconds())))

    async def _invalidate_active_challenges(self, mobile: str, purpose: str, channel: LoginChannel) -> None:
        await self.db.execute(
            update(OtpChallenge)
            .where(
                OtpChallenge.mobile_number == mobile,
                OtpChallenge.purpose == purpose,
                OtpChallenge.login_channel == channel.value,
                OtpChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=utc_now_naive())
        )

    async def _find_user_by_mobile(self, mobile: str) -> User | None:
        # Deterministic choice if an administrator created duplicate records for one number.
        return await self.db.scalar(
            select(User)
            .where(User.mobile_number == mobile)
            .order_by(case((User.status == "ACTIVE", 0), else_=1), User.created_at, User.id)
            .limit(1)
        )

    async def _find_or_create_onboarding_user(self, mobile: str) -> tuple[User, bool]:
        user = await self._find_user_by_mobile(mobile)
        if user:
            return user, False
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
        self.db.add(user)
        await self.db.flush()
        return user, True

    async def _issue_token_pair(
        self,
        user: User,
        channel: LoginChannel,
        device_id: str | None,
        *,
        session_type: SessionType = SessionType.ACCESS,
        family_id: str | None = None,
        device: DeviceInfo | None = None,
        previous: LoginSession | None = None,
    ) -> TokenPair:
        now = datetime.now(UTC)
        session_id = str(uuid4())
        access_exp = now + timedelta(minutes=self.settings.access_token_expires_minutes)
        refresh_exp = now + timedelta(days=self.settings.refresh_token_expires_days)
        access_payload = {
            "sub": user.id,
            "session_id": session_id,
            "token_type": session_type.value,
            "login_channel": channel.value,
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": access_exp,
        }
        refresh_payload = {
            "sub": user.id,
            "session_id": session_id,
            "token_type": REFRESH_TOKEN_TYPE,
            "session_type": session_type.value,
            "login_channel": channel.value,
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": refresh_exp,
            "secret": secrets.token_urlsafe(48),
        }
        access_token = jwt.encode(access_payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)
        encoded_refresh = jwt.encode(refresh_payload, self.settings.jwt_signing_secret, algorithm=self.settings.jwt_algorithm)
        self.db.add(
            LoginSession(
                id=session_id,
                user_id=user.id,
                refresh_token_hash=self._hash_refresh_token(encoded_refresh),
                device_id=device_id,
                user_agent=(self.client.user_agent or "")[:255] or None,
                ip_address=self.client.ip_address if self.settings.auth_audit_store_ip else None,
                login_channel=channel.value,
                session_type=session_type.value,
                family_id=family_id or session_id,
                device_type=_pick(device, "device_type", previous),
                device_name=_pick(device, "device_name", previous),
                app_version=_pick(device, "app_version", previous),
                push_token=_pick(device, "fcm_token", previous, "push_token"),
                created_at=now,
                expires_at=refresh_exp,
                last_activity_at=now,
                revoked_at=None,
            )
        )
        return TokenPair(access_token=access_token, refresh_token=encoded_refresh, expires_in=self.settings.access_token_expires_minutes * 60)

    def _hash_refresh_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _verify_refresh_token(self, token: str, hashed: str) -> bool:
        return hmac.compare_digest(self._hash_refresh_token(token), hashed)
