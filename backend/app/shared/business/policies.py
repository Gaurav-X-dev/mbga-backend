"""Tenancy and ownership policies shared by every business endpoint.

One place decides whether an actor may see a row, so a new endpoint cannot accidentally
widen access. Two rules run through all of it:

* A merchant actor sees only rows whose ``merchant_id`` is their own.
* A customer actor sees only rows whose ``customer_id`` is their own profile.

A row that belongs to someone else is reported as **404, not 403** — a 403 would confirm
the row exists, letting a caller enumerate other tenants' ids.
"""

from typing import Protocol

from fastapi import status
from sqlalchemy import Select

from app.modules.authentication.constants import LoginChannel
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError


class MerchantOwned(Protocol):
    merchant_id: str | None


class CustomerOwned(Protocol):
    customer_id: str


def not_found(code: str = "NOT_FOUND") -> ApiError:
    return ApiError(code, status.HTTP_404_NOT_FOUND)


def require_channel(actor: BusinessActor, channel: LoginChannel) -> None:
    """Reject a session issued for a different app.

    The auth layer already locks tokens to a channel; this guards handlers that are mounted
    under one prefix only, so a mounting mistake fails closed.
    """
    if actor.login_channel != channel:
        raise ApiError("TOKEN_CHANNEL_MISMATCH", status.HTTP_401_UNAUTHORIZED)


def scope_to_merchant(statement: Select, column, actor: BusinessActor) -> Select:
    """Filter a query to the actor's merchant. Call this on every merchant list query."""
    return statement.where(column == actor.require_merchant_id())


def scope_to_customer(statement: Select, column, actor: BusinessActor) -> Select:
    """Filter a query to the actor's own customer profile."""
    return statement.where(column == actor.require_customer_id())


def ensure_merchant_owns[T](row: T | None, actor: BusinessActor, *, code: str = "NOT_FOUND") -> T:
    """Return `row` when it belongs to the actor's merchant, otherwise raise 404."""
    if row is None or getattr(row, "merchant_id", None) != actor.require_merchant_id():
        raise not_found(code)
    return row


def ensure_customer_owns[T](row: T | None, actor: BusinessActor, *, code: str = "NOT_FOUND") -> T:
    """Return `row` when it belongs to the actor's customer profile, otherwise raise 404."""
    if row is None or getattr(row, "customer_id", None) != actor.require_customer_id():
        raise not_found(code)
    return row


def ensure_visible[T](row: T | None, actor: BusinessActor, *, code: str = "NOT_FOUND") -> T:
    """Ownership check for a resource both apps read (orders, invoices, payments).

    The actor's channel decides which rule applies, so one shared handler can serve the
    Customer and Merchant apps without either being able to reach the other's data.
    """
    if row is None:
        raise not_found(code)
    if actor.is_customer:
        return ensure_customer_owns(row, actor, code=code)
    return ensure_merchant_owns(row, actor, code=code)


def ensure_own_customer_id(requested_customer_id: str, actor: BusinessActor, *, code: str = "NOT_FOUND") -> str:
    """For paths like ``/customers/{id}/payments/summary`` that both apps call.

    A customer may only ever pass their own id; a merchant may pass any id belonging to
    their merchant, which the caller then verifies when it loads the row.
    """
    if actor.is_customer and requested_customer_id != actor.require_customer_id():
        raise not_found(code)
    return requested_customer_id
