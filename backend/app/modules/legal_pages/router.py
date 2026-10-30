from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.customers.dependencies import ActorDep
from app.modules.legal_pages.rendering import render_policy
from app.modules.legal_pages.schemas import (
    EditorResponse,
    PolicyContent,
    PublicPolicy,
    PublishRequest,
    RevisionResponse,
    SaveDraft,
)
from app.modules.legal_pages.service import LegalPageService
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
admin_router = APIRouter(
    prefix="/legal-pages/privacy-policy",
    tags=["Admin Privacy Policy"],
    dependencies=[Depends(require_login_channel(LoginChannel.ADMIN))],
)
public_router = APIRouter(prefix="/public", tags=["Public Legal Pages"])
html_router = APIRouter(tags=["Public Legal Pages"])
VIEW = Depends(require_permission("platform_settings.view"))
MANAGE = Depends(require_permission("platform_settings.manage"))
PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
}


@admin_router.get(
    "", response_model=EditorResponse, dependencies=[VIEW], responses=error_responses(401, 403)
)
async def editor(session: SessionDep):
    return await LegalPageService(session).editor()


@admin_router.put(
    "/draft",
    response_model=EditorResponse,
    dependencies=[MANAGE],
    responses=error_responses(401, 403, 409, 422),
)
async def save_draft(payload: SaveDraft, actor: ActorDep, session: SessionDep):
    return await LegalPageService(session).save(payload, actor)


@admin_router.post(
    "/publish",
    response_model=EditorResponse,
    dependencies=[MANAGE],
    responses=error_responses(401, 403, 409, 422),
)
async def publish(payload: PublishRequest, actor: ActorDep, session: SessionDep):
    return await LegalPageService(session).publish(payload, actor)


@admin_router.post(
    "/preview",
    response_class=HTMLResponse,
    dependencies=[VIEW],
    responses=error_responses(401, 403, 422),
)
async def preview(payload: PolicyContent):
    return HTMLResponse(render_policy(payload, preview=True), headers=PUBLIC_HEADERS)


@admin_router.get(
    "/revisions",
    response_model=list[RevisionResponse],
    dependencies=[VIEW],
    responses=error_responses(401, 403),
)
async def revisions(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 30):
    return await LegalPageService(session).revisions(limit)


@public_router.get("/privacy-policy", response_model=PublicPolicy, responses=error_responses(404))
async def public_policy(session: SessionDep, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await LegalPageService(session).public()


@html_router.get("/privacy-policy", response_class=HTMLResponse, include_in_schema=False)
@html_router.get("/privacy-policy/", response_class=HTMLResponse, include_in_schema=False)
async def public_html(session: SessionDep):
    published = await LegalPageService(session).public()
    return HTMLResponse(
        render_policy(published.content, published.revision, published.published_at),
        headers=PUBLIC_HEADERS,
    )
