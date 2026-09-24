"""Expense vocabulary and the category card a merchant starts with.

Categories are **rows, not an enum**: the Category sheet is filled from the API, and an
operator has to be able to add "Tolls" or "Godown Repairs" without a release. That is the
whole point of making them dynamic.

What stays in code is only the *starting set* every new merchant is seeded with, and the
icon keys the app renders. A category the merchant adds later gets its icon from this same
vocabulary, so the app never receives an icon name it has no drawable for.
"""

from decimal import Decimal
from enum import StrEnum


class ExpenseIcon(StrEnum):
    """Icon keys the merchant app has drawables for.

    A new category must pick one of these. Sending a free-text icon name would render as a
    blank tile in the list, which looks like a bug rather than a missing choice.
    """

    FUEL = "fuel"
    MAINTENANCE = "maintenance"
    SALARY = "salary"
    RENT = "rent"
    UTILITIES = "utilities"
    MISC = "misc"


#: The categories every merchant starts with, in the order the picker shows them.
#: Matches the Category sheet in the app today. Seeded per merchant on first touch, so a
#: merchant may rename, reorder, deactivate or add to them without affecting anyone else.
DEFAULT_CATEGORIES: tuple[tuple[str, str, ExpenseIcon], ...] = (
    ("FUEL", "Fuel", ExpenseIcon.FUEL),
    ("VEHICLE_MAINTENANCE", "Vehicle Maintenance", ExpenseIcon.MAINTENANCE),
    ("SALARY", "Salary", ExpenseIcon.SALARY),
    ("RENT", "Rent", ExpenseIcon.RENT),
    ("UTILITIES", "Utilities", ExpenseIcon.UTILITIES),
    ("MISCELLANEOUS", "Miscellaneous", ExpenseIcon.MISC),
)

#: The largest single expense the platform accepts. Well above a month's salary bill and
#: inside DECIMAL(12,2), so it catches a typo (a stray zero) rather than constraining
#: the business.
MAX_EXPENSE_AMOUNT = Decimal("99999999.99")

#: How far back an expense may be dated. Bills arrive late and a book gets caught up at
#: year end, so back-dating is allowed - but a date from another decade is a typo.
MAX_BACKDATE_DAYS = 1826  # five years

#: Free-text limits. The note is one line under the category in the list, not an essay.
MAX_NOTE_LENGTH = 255
MAX_LABEL_LENGTH = 60
MAX_CODE_LENGTH = 40
