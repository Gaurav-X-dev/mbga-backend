"""Operating values the platform admin changes from their own panel.

Distinct from `Settings`, which is read from the environment: those are deployment facts - where
the database is, which Firebase project to use - and changing one is a restart. These are
business decisions an operator makes during the working day, so they live in a row and take
effect on the next order rather than the next release.

Distinct from the `constants` table too, although both are "editable by an operator". That one
holds the labels behind dropdowns and is served to the apps on a public endpoint; this holds
values the backend computes with, and is admin-only.

**One row, typed columns.** A key/value table would need every reader to parse a string and
decide what to do when it is not a number. A column per setting costs a migration each time and
gives the value a type, a default and a range the database itself enforces.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.database.base import Base

#: The one row. A fixed id rather than an autoincrement because there is exactly one of these
#: and a second would be a bug - `SELECT ... WHERE id = SINGLETON_ID` cannot accidentally read
#: whichever row happened to be written last.
SINGLETON_ID = "platform"

#: What a fresh install starts with, and what is used if the row is somehow missing. 16:00 IST is
#: the cut-off the platform shipped with (spec §6.2).
DEFAULT_ORDER_CUTOFF_HOUR = 16


class PlatformSettings(Base):
    """Platform-wide operating values. Exactly one row, id `platform`."""

    __tablename__ = "platform_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # The hour, IST, after which an order is delivered the next day instead of today. A whole
    # hour on a wall clock, because that is how the cut-off is told to a customer and worked to
    # in the godown; half past anything would have to be explained on every screen.
    order_cutoff_hour: Mapped[int] = mapped_column(Integer, default=DEFAULT_ORDER_CUTOFF_HOUR)
    # Who last changed any of this. The trail for a value that silently moves every order's
    # promised date is worth more than the value itself.
    updated_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
