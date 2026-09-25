"""Stock alerts, derived from live counts (spec §11.1, §18.6: "Alerts are derived from live counts").

Nothing here is stored. An alert is a reading of the counts as they are right now, so it
appears and disappears the moment a movement changes them - a refill clears the low-stock
warning without anything having to go back and mark it resolved. Storing alerts is how a
warehouse screen ends up showing a shortage that was filled yesterday.

The thresholds are spec §11.1's:

    filled < reorderThreshold          -> WARNING
    filled < reorderThreshold / 2      -> CRITICAL   (the same shortage, escalated)
    damaged >= 5                       -> INFO

Low stock raises **one** alert, not two: below half the threshold is the same shortage seen
later, so it replaces the warning rather than sitting beside it. Two rows for one problem is
how an alert list stops being read.
"""

from app.modules.inventory.constants import DAMAGED_ALERT_FLOOR
from app.modules.inventory.models import StockItem
from app.modules.notifications.constants import Severity

#: Stable ids, so the app can dedupe and animate rather than re-rendering the whole list.
#: They are derived, not stored - the same shortage always reports the same id.
LOW_PREFIX = "SA-LOW"
DAMAGED_PREFIX = "SA-DMG"


class StockAlert:
    """One derived alert. Not a table row."""

    __slots__ = ("cylinder_type", "id", "message", "severity")

    def __init__(self, id: str, cylinder_type: str, severity: Severity, message: str) -> None:
        self.id = id
        self.cylinder_type = cylinder_type
        self.severity = severity
        self.message = message


def low_stock(item: StockItem, label: str) -> StockAlert | None:
    """A refill warning, escalated to critical below half the threshold.

    A threshold of zero means the type is not being tracked against a reorder line, so it
    raises nothing - otherwise every untracked cylinder would report a permanent shortage.
    """
    if item.reorder_threshold <= 0 or item.filled >= item.reorder_threshold:
        return None
    # Integer division: a threshold of 50 escalates below 25, which is what "< threshold/2"
    # means for whole cylinders.
    critical = item.filled < item.reorder_threshold // 2
    return StockAlert(
        id=f"{LOW_PREFIX}-{item.cylinder_type}",
        cylinder_type=item.cylinder_type,
        severity=Severity.CRITICAL if critical else Severity.WARNING,
        message=(
            f"{label} filled stock ({item.filled}) is below the reorder threshold "
            f"({item.reorder_threshold})."
        ),
    )


def damaged_pile(item: StockItem, label: str) -> StockAlert | None:
    """Enough damaged cylinders to be worth a trip back to BPCL.

    INFO, because nothing is blocked: damaged cylinders are already out of the sellable count.
    It is a reminder that capital is sitting in a corner of the godown.
    """
    if item.damaged < DAMAGED_ALERT_FLOOR:
        return None
    return StockAlert(
        id=f"{DAMAGED_PREFIX}-{item.cylinder_type}",
        cylinder_type=item.cylinder_type,
        severity=Severity.INFO,
        message=f"{item.damaged} damaged {label} cylinders awaiting return to BPCL.",
    )


def derive(items: list[tuple[StockItem, str]]) -> list[StockAlert]:
    """Every alert the given rows raise, worst first.

    Ordered by severity because the screen shows the list truncated and the dashboard takes
    the top few (spec §14): a critical shortage must not be pushed out of view by three
    informational notes about damaged cylinders.
    """
    found: list[StockAlert] = []
    for item, label in items:
        for alert in (low_stock(item, label), damaged_pile(item, label)):
            if alert is not None:
                found.append(alert)
    rank = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    # Cylinder type breaks the tie, so the same counts always produce the same order and the
    # list does not reshuffle between refreshes.
    return sorted(found, key=lambda alert: (rank[alert.severity], alert.cylinder_type))
