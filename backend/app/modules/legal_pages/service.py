from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.modules.legal_pages.defaults import initial_policy
from app.modules.legal_pages.models import LegalDocument, LegalDocumentRevision
from app.modules.legal_pages.schemas import (
    EditorResponse,
    PolicyContent,
    PublicPolicy,
    RevisionResponse,
)
from app.shared.date_time.business_calendar import business_today
from app.shared.exceptions.api_error import ApiError

SLUG = "privacy-policy"


def publication_issues(content):
    issues = []
    if not content.contact_email and not content.contact_url:
        issues.append("Add a verified privacy email or privacy contact URL.")
    if content.background_location == "UNCONFIRMED":
        issues.append("Confirm whether the Rider app uses foreground-only or background location.")
    if not content.sdk_disclosure:
        issues.append(
            "Describe the actual service providers and mobile SDKs, including any analytics, crash reporting or advertising SDKs."
        )
    if content.effective_date > business_today():
        issues.append("Effective date cannot be in the future when publishing.")
    return issues


class LegalPageService:
    def __init__(self, session):
        self.session = session

    async def editor(self):
        row = await self.session.get(LegalDocument, SLUG, populate_existing=True)
        if row is None:
            draft = initial_policy()
            return EditorResponse(
                revision=0, draft=draft, publication_issues=publication_issues(draft)
            )
        draft = PolicyContent.model_validate_json(row.draft_json)
        return EditorResponse(
            revision=row.revision,
            draft=draft,
            published=PolicyContent.model_validate_json(row.published_json)
            if row.published_json
            else None,
            published_revision=row.published_revision,
            published_at=row.published_at,
            updated_at=row.updated_at,
            updated_by=row.updated_by,
            publication_issues=publication_issues(draft),
        )

    @staticmethod
    def conflict():
        return ApiError(
            "LEGAL_PAGE_CONFLICT",
            409,
            "This policy changed in another session. Reload before saving or publishing.",
        )

    def history(self, action, revision, content_json, actor, now):
        self.session.add(
            LegalDocumentRevision(
                id=str(uuid4()),
                slug=SLUG,
                revision=revision,
                action=action,
                content_json=content_json,
                actor_id=actor.user_id,
                actor_name=actor.display_name,
                created_at=now,
            )
        )

    async def save(self, payload, actor):
        now = datetime.now(UTC)
        next_revision = payload.expected_revision + 1
        content_json = payload.content.model_dump_json(by_alias=True)
        try:
            if payload.expected_revision == 0:
                self.session.add(
                    LegalDocument(
                        slug=SLUG,
                        draft_json=content_json,
                        revision=1,
                        updated_at=now,
                        updated_by=actor.display_name,
                    )
                )
                await self.session.flush()
            else:
                result = await self.session.execute(
                    update(LegalDocument)
                    .where(
                        LegalDocument.slug == SLUG,
                        LegalDocument.revision == payload.expected_revision,
                    )
                    .values(
                        draft_json=content_json,
                        revision=next_revision,
                        updated_at=now,
                        updated_by=actor.display_name,
                    )
                )
                if result.rowcount != 1:
                    await self.session.rollback()
                    raise self.conflict()
            self.history("DRAFT_SAVED", next_revision, content_json, actor, now)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise self.conflict() from exc
        return await self.editor()

    async def publish(self, payload, actor):
        row = await self.session.scalar(
            select(LegalDocument)
            .where(LegalDocument.slug == SLUG)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.revision != payload.expected_revision:
            raise self.conflict()
        content = PolicyContent.model_validate_json(row.draft_json)
        issues = publication_issues(content)
        if issues:
            raise ApiError(
                "LEGAL_PAGE_NOT_READY",
                422,
                "Complete the policy details before publishing.",
                fields=[
                    {"field": "content", "code": "incomplete", "message": item} for item in issues
                ],
            )
        now = datetime.now(UTC)
        row.revision += 1
        row.published_revision = row.revision
        row.published_json = row.draft_json
        row.published_at = row.updated_at = now
        row.updated_by = actor.display_name
        self.history("PUBLISHED", row.revision, row.published_json, actor, now)
        await self.session.commit()
        return await self.editor()

    async def public(self):
        row = await self.session.get(LegalDocument, SLUG, populate_existing=True)
        if row is None or not row.published_json:
            raise ApiError(
                "LEGAL_PAGE_NOT_PUBLISHED", 404, "This privacy policy has not been published yet."
            )
        return PublicPolicy(
            revision=row.published_revision,
            published_at=row.published_at,
            content=PolicyContent.model_validate_json(row.published_json),
        )

    async def revisions(self, limit=30):
        rows = await self.session.scalars(
            select(LegalDocumentRevision)
            .where(LegalDocumentRevision.slug == SLUG)
            .order_by(LegalDocumentRevision.revision.desc())
            .limit(limit)
        )
        return [
            RevisionResponse(
                id=r.id,
                revision=r.revision,
                action=r.action,
                actor_name=r.actor_name,
                created_at=r.created_at,
                content=PolicyContent.model_validate_json(r.content_json),
            )
            for r in rows
        ]
