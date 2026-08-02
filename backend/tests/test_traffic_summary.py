from datetime import datetime, timezone

from app.routers.traffic import _add_open_bucket, _compact_range
from app.services.traffic_service import _billing_cycle_start


def _report() -> dict:
    return {
        "start": "2026-08-02T00:00:00+00:00",
        "end": "2026-08-03T00:00:00+00:00",
        "rxBytes": 100,
        "txBytes": 50,
        "totalBytes": 150,
        "hasGap": False,
        "buckets": [],
        "daily": [],
    }


def test_open_bucket_is_added_to_matching_range() -> None:
    report = _report()

    _add_open_bucket(
        report,
        {
            "currentBucketStart": "2026-08-02T09:30:00Z",
            "currentBucketRxBytes": 25,
            "currentBucketTxBytes": 10,
        },
    )

    assert report["rxBytes"] == 125
    assert report["txBytes"] == 60
    assert report["totalBytes"] == 185
    assert report["openBucket"]["bucketStart"] == "2026-08-02T09:30:00Z"
    assert _compact_range(report)["hasData"] is True


def test_open_bucket_outside_range_is_ignored() -> None:
    report = _report()

    _add_open_bucket(
        report,
        {
            "currentBucketStart": "2026-08-03T00:00:00Z",
            "currentBucketRxBytes": 25,
            "currentBucketTxBytes": 10,
        },
    )

    assert report["rxBytes"] == 100
    assert report["txBytes"] == 50
    assert report["totalBytes"] == 150
    assert "openBucket" not in report
    assert _compact_range(report)["hasData"] is False


def test_billing_cycle_uses_current_or_previous_month() -> None:
    before_start = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
    after_start = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)

    assert _billing_cycle_start(before_start, 20) == datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert _billing_cycle_start(after_start, 20) == datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_billing_cycle_clamps_day_to_short_month_end() -> None:
    before_february_end = datetime(2026, 2, 15, 12, tzinfo=timezone.utc)
    after_february_end = datetime(2026, 2, 28, 12, tzinfo=timezone.utc)

    assert _billing_cycle_start(before_february_end, 31) == datetime(2026, 1, 31, tzinfo=timezone.utc)
    assert _billing_cycle_start(after_february_end, 31) == datetime(2026, 2, 28, tzinfo=timezone.utc)
