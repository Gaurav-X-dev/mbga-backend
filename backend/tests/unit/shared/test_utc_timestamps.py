from app.shared.middleware.utc_timestamps import normalize_utc_timestamps


def test_naive_iso_datetimes_are_marked_as_utc_recursively():
    payload = {
        "createdAt": "2026-10-14T09:55:00",
        "rows": [{"reviewedAt": "2026-10-14T09:56:00.123456"}],
    }

    assert normalize_utc_timestamps(payload) == {
        "createdAt": "2026-10-14T09:55:00Z",
        "rows": [{"reviewedAt": "2026-10-14T09:56:00.123456Z"}],
    }


def test_dates_offsets_and_business_strings_are_unchanged():
    payload = {
        "deliveryDate": "2026-10-14",
        "utc": "2026-10-14T09:55:00Z",
        "offset": "2026-10-14T15:25:00+05:30",
        "note": "Created 2026-10-14T09:55:00 by operator",
    }

    assert normalize_utc_timestamps(payload) == payload
