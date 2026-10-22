"""Persistence used only by the v2 multi-image KYC contract.

The table deliberately has no database foreign keys.  Production's v1 tables are left
unchanged; ownership and file existence are checked by the v2 service in the same database
transaction that creates these mappings.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class CustomerDocumentFileV2(Base):
    __tablename__ = "customer_document_files_v2"
    __table_args__ = (
        Index(
            "ix_customer_document_files_v2_current",
            "customer_id",
            "document_type",
            "superseded_at",
        ),
        Index("ix_customer_document_files_v2_file", "file_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(36), index=True)
    document_type: Mapped[str] = mapped_column(String(80))
    file_id: Mapped[str] = mapped_column(String(60))
    side: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
