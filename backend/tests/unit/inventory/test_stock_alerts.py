"""Alert derivation, checked against the counts that produce it (spec §11.1).

Alerts are the one part of the warehouse the app does not get told - it is computed from the
counts on every read. So these tests are about the boundaries, because a threshold that fires
one cylinder late is a godown that runs out on a day nobody was warned about.
"""

from datetime import UTC, datetime

import pytest

from app.modules.inventory.alerts import DAMAGED_PREFIX, LOW_PREFIX, derive, low_stock
from app.modules.inventory.constants import DAMAGED_ALERT_FLOOR
from app.modules.inventory.models import StockItem
from app.modules.notifications.constants import Severity

pytestmark = [pytest.mark.unit]

LABEL = "19 KG"


def item(*, filled: int = 100, empty: int = 0, damaged: int = 0, threshold: int = 50) -> StockItem:
    now = datetime.now(UTC)
    return StockItem(
        id="si-1",
        merchant_id="m-1",
        cylinder_type="LPG_19KG",
        filled=filled,
        empty=empty,
        damaged=damaged,
        reorder_threshold=threshold,
        created_at=now,
        updated_at=now,
    )


# --- Low stock ------------------------------------------------------------------------------


def test_stock_at_the_threshold_is_not_an_alert():
    """"below the reorder threshold" (§11.1), so equal is still fine.

    Off by one here means a warning on the day stock is exactly where it is supposed to be.
    """
    assert low_stock(item(filled=50, threshold=50), LABEL) is None


def test_one_below_the_threshold_warns():
    alert = low_stock(item(filled=49, threshold=50), LABEL)

    assert alert is not None
    assert alert.severity is Severity.WARNING
    assert alert.id == f"{LOW_PREFIX}-LPG_19KG"


def test_below_half_the_threshold_escalates_to_critical():
    assert low_stock(item(filled=24, threshold=50), LABEL).severity is Severity.CRITICAL


def test_exactly_half_the_threshold_is_still_only_a_warning():
    """`< threshold/2`, not `<=`. 25 of 50 is low, not desperate."""
    assert low_stock(item(filled=25, threshold=50), LABEL).severity is Severity.WARNING


def test_zero_stock_is_critical():
    assert low_stock(item(filled=0, threshold=50), LABEL).severity is Severity.CRITICAL


def test_an_odd_threshold_halves_downwards():
    """A threshold of 5 escalates below 2, because two cylinders is not two and a half."""
    assert low_stock(item(filled=2, threshold=5), LABEL).severity is Severity.WARNING
    assert low_stock(item(filled=1, threshold=5), LABEL).severity is Severity.CRITICAL


def test_a_type_with_no_threshold_never_warns():
    """Otherwise every untracked cylinder would report a permanent shortage."""
    assert low_stock(item(filled=0, threshold=0), LABEL) is None


def test_the_message_carries_both_numbers():
    """The spec's wording. Staff act on the gap, so both figures have to be in it."""
    alert = low_stock(item(filled=42, threshold=50), "47.5 KG L")

    assert alert.message == "47.5 KG L filled stock (42) is below the reorder threshold (50)."


# --- Damaged pile ---------------------------------------------------------------------------


def test_the_damaged_pile_is_reported_only_once_it_is_worth_a_trip():
    below = derive([(item(damaged=DAMAGED_ALERT_FLOOR - 1), LABEL)])
    at_floor = derive([(item(damaged=DAMAGED_ALERT_FLOOR), LABEL)])

    assert below == []
    assert [alert.id for alert in at_floor] == [f"{DAMAGED_PREFIX}-LPG_19KG"]
    assert at_floor[0].severity is Severity.INFO


def test_the_damaged_alert_is_informational_because_nothing_is_blocked():
    """Damaged cylinders are already out of the sellable count; this is tied-up capital."""
    alert = derive([(item(damaged=7), LABEL)])[0]

    assert alert.severity is Severity.INFO
    assert alert.message == "7 damaged 19 KG cylinders awaiting return to BPCL."


# --- Together -------------------------------------------------------------------------------


def test_a_shortage_raises_one_alert_not_two():
    """Below half the threshold replaces the warning rather than joining it."""
    alerts = derive([(item(filled=10, threshold=50), LABEL)])

    assert len(alerts) == 1
    assert alerts[0].severity is Severity.CRITICAL


def test_low_stock_and_a_damaged_pile_are_separate_problems():
    alerts = derive([(item(filled=10, threshold=50, damaged=9), LABEL)])

    assert [alert.severity for alert in alerts] == [Severity.CRITICAL, Severity.INFO]


def test_the_worst_alert_is_first():
    """The dashboard takes the top few (§14), so ordering decides what gets seen."""
    rows = [
        (item(damaged=6), "19 KG"),
        (item(filled=45, threshold=50), "5 KG"),
        (item(filled=5, threshold=50), "422 KG Hippo"),
    ]

    severities = [alert.severity for alert in derive(rows)]

    assert severities == [Severity.CRITICAL, Severity.WARNING, Severity.INFO]


def test_healthy_stock_raises_nothing():
    assert derive([(item(filled=200, threshold=50, damaged=1), LABEL)]) == []


def test_no_rows_means_no_alerts():
    """A merchant who has never recorded stock has not run out of anything."""
    assert derive([]) == []
