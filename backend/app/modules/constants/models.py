"""The `constants` table: key/value reference data the apps read.

Deliberately plain - `id`, `const_key`, `const_value` and nothing else. It holds the fixed
vocabularies an operator may want to reword without a deploy, such as the delivery states or
the label shown for a document type.

**What does not belong here.** Anything the backend validates against. A customer type or a
document type has its authority in the code enum the validators use; copying those into rows
would let someone add a row the API then refuses, so the app would offer a choice that cannot
be saved. The seeder writes those rows *from* the enums for that reason, and a test asserts
the two still agree.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base


class Constant(Base):
    __tablename__ = "constants"
    __table_args__ = (
        UniqueConstraint("const_key", name="uq_constants_const_key"),
        Index("ix_constants_group", "const_group"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # What the app sends back to the API, e.g. "RETAIL".
    const_key: Mapped[str] = mapped_column(String(100))
    # What the app shows the user, e.g. "Retail".
    const_value: Mapped[str] = mapped_column(String(255))
    # Which dropdown the row belongs to. Without it every option arrives in one undivided
    # list and the app cannot tell a customer type from a document type.
    const_group: Mapped[str] = mapped_column(String(50))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
