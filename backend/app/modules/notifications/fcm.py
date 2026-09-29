"""Firebase Cloud Messaging, HTTP v1.

No Firebase SDK. The whole protocol is a signed JWT exchanged for an access token, then one
POST per device, and the three pieces that needs - `pyjwt`, `cryptography` and `httpx` - are
already dependencies of this project. Pulling in `firebase-admin` for that would add a large
transitive tree to do the same work.

The legacy `Authorization: key=AAAA...` endpoint is deliberately not used: Google shut it
down in June 2024, so a service account is the only way in.

**Nothing here raises for a delivery failure.** The dispatcher decides what a failure means,
because a notification must never be the thing that fails a business write, and the two
outcomes it has to tell apart - "retry this later" and "this token is dead, forget it" - are
its decision, not the transport's.
"""

import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_LIFETIME_SECONDS = 3600
#: Refresh the access token a little early rather than racing its expiry mid-batch.
TOKEN_REFRESH_MARGIN = 120
SEND_TIMEOUT_SECONDS = 10

#: FCM's way of saying "this device is gone". The token is deleted rather than retried -
#: retrying a dead token forever is how an outbox stops draining.
DEAD_TOKEN_STATUSES = frozenset({404})
DEAD_TOKEN_ERRORS = frozenset({"UNREGISTERED", "INVALID_ARGUMENT"})

#: "This token belongs to a different Firebase project." Deliberately **not** a dead token:
#: the device is fine, the routing is wrong, and deleting a working token because the wrong
#: project was configured would sign the user out of push until they reinstalled. It is
#: reported and retried instead, so fixing the configuration delivers the backlog.
MISROUTED_ERRORS = frozenset({"SENDER_ID_MISMATCH", "THIRD_PARTY_AUTH_ERROR"})


@dataclass(frozen=True)
class SendResult:
    """What happened to one device."""

    ok: bool
    #: True when the token itself is invalid and should be removed rather than retried.
    token_dead: bool = False
    #: True when the token is valid but was sent through the wrong Firebase project. A
    #: configuration problem, never the device's fault - so the token is kept.
    misrouted: bool = False
    error: str | None = None


@dataclass(frozen=True)
class PushMessage:
    """One notification, as FCM needs it."""

    title: str
    body: str
    #: Delivered as `data`, so the app can deep-link without parsing the title.
    data: dict[str, str]


class FcmCredentials:
    """A service-account JSON, loaded once.

    The file is read from disk rather than from an environment variable: a PEM private key
    does not survive being pasted into `.env` intact, and a file can be given filesystem
    permissions that an environment variable cannot.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        missing = [k for k in ("project_id", "private_key", "client_email", "token_uri") if not payload.get(k)]
        if missing:
            raise ValueError(f"{self.path} is not a service-account key: missing {', '.join(missing)}")
        self.project_id: str = payload["project_id"]
        self.client_email: str = payload["client_email"]
        self.token_uri: str = payload["token_uri"]
        self._private_key: str = payload["private_key"]

    def assertion(self, *, now: int | None = None) -> str:
        """The signed JWT Google exchanges for an access token."""
        issued = now or int(time.time())
        return jwt.encode(
            {
                "iss": self.client_email,
                "scope": FCM_SCOPE,
                "aud": self.token_uri,
                "iat": issued,
                "exp": issued + TOKEN_LIFETIME_SECONDS,
            },
            self._private_key,
            algorithm="RS256",
        )


class FcmClient:
    """Sends one message to one device token at a time.

    FCM v1 has no multicast endpoint - the old `registration_ids` array went with the legacy
    API - so a notification for five devices is five calls. They share one access token and
    one HTTP connection, which is what `aclose` is for.
    """

    def __init__(self, credentials: FcmCredentials, *, client: httpx.AsyncClient | None = None) -> None:
        self.credentials = credentials
        self._client = client or httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS)
        self._owns_client = client is None
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def send_url(self) -> str:
        return f"https://fcm.googleapis.com/v1/projects/{self.credentials.project_id}/messages:send"

    async def access_token(self) -> str:
        """A cached OAuth2 access token, refreshed shortly before it expires."""
        if self._access_token and time.time() < self._expires_at:
            return self._access_token
        response = await self._client.post(
            self.credentials.token_uri,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self.credentials.assertion(),
            },
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", TOKEN_LIFETIME_SECONDS)) - TOKEN_REFRESH_MARGIN
        return self._access_token

    async def send(self, token: str, message: PushMessage) -> SendResult:
        """Deliver to one device. Never raises - the outcome is the return value."""
        try:
            access = await self.access_token()
        except Exception as error:  # noqa: BLE001 - a bad credential must not crash the worker
            return SendResult(ok=False, error=f"auth: {type(error).__name__}: {error}"[:200])

        payload = {
            "message": {
                "token": token,
                "notification": {"title": message.title, "body": message.body},
                # Every value must be a string; FCM rejects a data map with numbers in it.
                "data": {key: str(value) for key, value in message.data.items()},
                "android": {"priority": "high"},
                "apns": {"headers": {"apns-priority": "10"}},
            }
        }
        try:
            response = await self._client.post(
                self.send_url,
                json=payload,
                headers={"Authorization": f"Bearer {access}"},
            )
        except httpx.HTTPError as error:
            # A network failure is worth retrying; the token is not implicated.
            return SendResult(ok=False, error=f"network: {type(error).__name__}"[:200])

        if response.is_success:
            return SendResult(ok=True)
        status_name = _error_status(response)
        return SendResult(
            ok=False,
            token_dead=_is_dead_token(response, status_name),
            misrouted=status_name in MISROUTED_ERRORS,
            error=f"{response.status_code}: {response.text[:160]}",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _error_status(response: httpx.Response) -> str | None:
    """The machine-readable error name FCM put in the body, if there is one."""
    try:
        detail = response.json().get("error", {})
    except ValueError:
        return None
    if not isinstance(detail, dict):
        return None
    named = detail.get("status")
    if named:
        return named
    for item in detail.get("details", []):
        if isinstance(item, dict) and item.get("errorCode"):
            return item["errorCode"]
    return None


def _is_dead_token(response: httpx.Response, status_name: str | None) -> bool:
    """Whether FCM is saying this device is gone for good.

    A 404 means the token is unknown. A 400 can be a bad token, a bad message, or a token
    from another project, so the error name inside the body is what decides - treating
    every 400 as a dead token would quietly delete working tokens the day a payload field
    is wrong or a credential is misconfigured.
    """
    if response.status_code in DEAD_TOKEN_STATUSES:
        return True
    if response.status_code != 400:
        return False
    return status_name in DEAD_TOKEN_ERRORS
