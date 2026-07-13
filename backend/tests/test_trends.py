import pytest
from datetime import date

from app.trends import bucket_bounds, bucket_day_totals


def test_bucket_bounds_week_is_monday_to_sunday():
    # 2026-07-15 is a Wednesday
    start, end = bucket_bounds(date(2026, 7, 15), "week")
    assert start == date(2026, 7, 13)  # Monday
    assert end == date(2026, 7, 19)  # Sunday


def test_bucket_bounds_month_handles_december_wraparound():
    start, end = bucket_bounds(date(2026, 12, 10), "month")
    assert start == date(2026, 12, 1)
    assert end == date(2026, 12, 31)


def test_bucket_bounds_month_regular():
    start, end = bucket_bounds(date(2026, 7, 15), "month")
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_bucket_day_totals_averages_over_logged_days_only():
    day_totals = {
        date(2026, 7, 13): {"iron": 10.0, "vitamin_c": 20.0},
        date(2026, 7, 14): {"iron": 20.0},  # no vitamin_c logged this day
        date(2026, 7, 20): {"iron": 5.0},  # different week
    }
    buckets = bucket_day_totals(day_totals, "week")
    assert len(buckets) == 2

    week1 = buckets[0]
    assert week1.bucket_start == date(2026, 7, 13)
    assert week1.logged_days == 2
    assert week1.avg_nutrients["iron"] == pytest.approx(15.0)  # (10+20)/2
    assert week1.avg_nutrients["vitamin_c"] == pytest.approx(10.0)  # 20/2, not 20/1

    week2 = buckets[1]
    assert week2.logged_days == 1
    assert week2.avg_nutrients["iron"] == pytest.approx(5.0)


def test_bucket_day_totals_sorted_by_bucket_start():
    day_totals = {
        date(2026, 8, 1): {"iron": 1.0},
        date(2026, 7, 1): {"iron": 2.0},
    }
    buckets = bucket_day_totals(day_totals, "month")
    assert [b.bucket_start for b in buckets] == [date(2026, 7, 1), date(2026, 8, 1)]
