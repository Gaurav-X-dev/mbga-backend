from datetime import UTC, datetime, timedelta

from scripts.send_credit_reminders import quiet, reminder_due


def test_quiet_hours_work_across_midnight():
    assert quiet(22, 21, 8)
    assert quiet(7, 21, 8)
    assert not quiet(8, 21, 8)
    assert not quiet(14, 21, 8)


def test_reminder_waits_for_interval():
    now = datetime(2026, 10, 11, 10, tzinfo=UTC)
    assert not reminder_due(
        now,
        last_sent_at=now - timedelta(hours=23),
        reminder_count=1,
        max_count=3,
        interval_hours=24,
    )
    assert reminder_due(
        now,
        last_sent_at=now - timedelta(hours=24),
        reminder_count=1,
        max_count=3,
        interval_hours=24,
    )


def test_reminder_stops_at_maximum_count():
    assert not reminder_due(
        datetime.now(UTC),
        last_sent_at=None,
        reminder_count=3,
        max_count=3,
        interval_hours=1,
    )
