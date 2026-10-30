"""Isolated public legal content; no business-account or payment tables are modified."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class LegalDocument(Base):
    __tablename__ = "legal_documents"
    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    draft_json: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql", "mariadb"))
    published_json: Mapped[str | None] = mapped_column(
        Text().with_variant(MEDIUMTEXT(), "mysql", "mariadb"), nullable=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    published_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(160))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LegalDocumentRevision(Base):
    __tablename__ = "legal_document_revisions"
    __table_args__ = (UniqueConstraint("slug", "revision", name="uq_legal_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    content_json: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql", "mariadb"))
    actor_id: Mapped[str] = mapped_column(String(36))
    actor_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
