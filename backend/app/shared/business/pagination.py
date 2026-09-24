"""Pagination shared by business list endpoints.

Shape matches the existing merchant/user/delivery list responses — ``items``, ``total``,
``limit``, ``offset`` — so the mobile apps and the web panel see one format across the
whole API. Spec §1 says the apps have a ``Paginated<T>`` type and their services unwrap it,
and they ignore the extra ``limit``/``offset`` keys.
"""

from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class Page:
    """Validated paging window from the query string."""

    limit: int
    offset: int


def page_params(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Rows per page."),
    offset: int = Query(0, ge=0, description="Rows to skip."),
) -> Page:
    """FastAPI dependency. Bounds are enforced by Query, so a 422 names the parameter."""
    return Page(limit=limit, offset=offset)


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


async def paginate(session: AsyncSession, statement: Select, page: Page) -> tuple[list, int]:
    """Run `statement` for one page and count the full result set.

    The count reuses the caller's filters through a subquery, so a list and its total can
    never disagree about scoping — the commonest way a tenancy filter gets missed.
    """
    total = await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = (await session.execute(statement.limit(page.limit).offset(page.offset))).unique().all()
    return [row[0] if len(row) == 1 else row for row in rows], total
