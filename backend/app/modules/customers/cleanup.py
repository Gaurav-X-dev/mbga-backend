"""Cleanup for KYC uploads that were staged but never attached to a registration."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import CustomerDocument
from app.shared.storage.provider import StorageProvider


@dataclass(frozen=True)
class OrphanedUploadCleanupResult:
    dry_run: bool
    retention_hours: int
    expired_before: datetime
    file_ids: list[str]

    @property
    def count(self) -> int:
        return len(self.file_ids)


class OrphanedUploadCleanupService:
    """Deletes only expired staged uploads.

    A staged upload is safe to purge when it has no customer id and no finalized timestamp.
    Finalized or referenced documents are outside this query, so a retry cannot remove a
    document already attached to a customer.
    """

    def __init__(self, session: AsyncSession, storage: StorageProvider) -> None:
        self.session = session
        self.storage = storage

    async def cleanup(
        self,
        *,
        retention_hours: int,
        dry_run: bool = True,
        now: datetime | None = None,
        limit: int = 500,
    ) -> OrphanedUploadCleanupResult:
        moment = now or datetime.now(UTC)
        cutoff = moment - timedelta(hours=retention_hours)
        documents = list(
            await self.session.scalars(
                select(CustomerDocument)
                .where(
                    CustomerDocument.customer_id.is_(None),
                    CustomerDocument.finalized_at.is_(None),
                    CustomerDocument.created_at < cutoff,
                )
                .order_by(CustomerDocument.created_at)
                .limit(limit)
            )
        )
        file_ids = [document.file_id or document.id for document in documents]
        if not dry_run:
            for document in documents:
                await self.storage.delete(document.storage_key)
                await self.session.delete(document)
            await self.session.flush()
        return OrphanedUploadCleanupResult(
            dry_run=dry_run,
            retention_hours=retention_hours,
            expired_before=cutoff,
            file_ids=file_ids,
        )
