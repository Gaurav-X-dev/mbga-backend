"""A `from`/`to` filter that takes a date or a timestamp.

`from` and `to` mean a date on the expenses and pricing screens and a timestamp on the reports
screen - one parameter name, two types, nothing on the wire to tell them apart. An app that
sent `from=2026-10-04T13:37:00Z` to all three got a report and two refusals reading

    query.from: Datetimes provided to dates should have zero time - e.g. be exact dates

which is correct, and means nothing to somebody who tapped "Last 7 days".
"""

from datetime import date, datetime

import pytest

from app.shared.date_time.query_params import as_business_date

pytestmark = pytest.mark.unit


# --- What a client might send --------------------------------------------------------------------


def test_a_plain_date_is_unchanged():
    assert as_business_date("2026-10-04") == date(2026, 10, 4)


def test_a_timestamp_is_reduced_to_its_day():
    """The case that was refused."""
    assert as_business_date("2026-10-04T13:37:00Z") == date(2026, 10, 4)


def test_midnight_with_a_z_is_the_same_day():
    assert as_business_date("2026-10-04T00:00:00Z") == date(2026, 10, 4)


def test_a_naive_timestamp_is_taken_as_it_reads():
    """No offset means the client did not say; reading it as UTC would shift their day."""
    assert as_business_date("2026-10-04T23:50:00") == date(2026, 10, 4)


def test_a_date_object_passes_through():
    assert as_business_date(date(2026, 10, 4)) == date(2026, 10, 4)


def test_a_datetime_object_is_reduced():
    assert as_business_date(datetime(2026, 10, 4, 13, 37)) == date(2026, 10, 4)


# --- The offset is read in IST ---------------------------------------------------------------------


def test_late_utc_is_the_next_day_in_india():
    """18:40Z is twenty past midnight in Delhi, and the person picked an Indian calendar."""
    assert as_business_date("2026-10-04T18:40:00Z") == date(2026, 10, 5)


def test_an_ist_offset_keeps_its_own_day():
    assert as_business_date("2026-10-04T13:37:00+05:30") == date(2026, 10, 4)


def test_the_last_moment_of_an_ist_day_stays_on_it():
    assert as_business_date("2026-10-04T23:59:59+05:30") == date(2026, 10, 4)


# --- What it refuses to guess at ---------------------------------------------------------------------


def test_nonsense_is_handed_on_untouched():
    """So the field reports its own error, naming the type the caller actually used."""
    assert as_business_date("last tuesday") == "last tuesday"


def test_an_empty_string_is_handed_on():
    assert as_business_date("") == ""


def test_a_number_is_handed_on():
    assert as_business_date(1759600000) == 1759600000
