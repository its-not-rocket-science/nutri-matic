"""Buckets per-day nutrient totals into weekly or monthly averages for the
diary trends view.

Averaging denominator is always the count of *logged* days in the bucket
(days with at least one diary entry), not the bucket's full calendar
length — an unlogged day isn't "zero intake", it's missing data, and
folding it into the average would understate real intake on however many
days a user actually did log. This mirrors the diary day view's own
approach of just omitting nutrients it has no data for, rather than
silently treating "no data" as "none consumed".
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

GroupBy = Literal["week", "month"]


def bucket_bounds(d: date, group_by: GroupBy) -> tuple[date, date]:
    """The (start, end) dates of the week/month bucket a given day falls
    into — Monday-Sunday for week (matches the meal plan's week framing),
    calendar month for month."""
    if group_by == "week":
        monday = d - timedelta(days=d.weekday())
        return monday, monday + timedelta(days=6)

    first = d.replace(day=1)
    if first.month == 12:
        last = date(first.year, 12, 31)
    else:
        last = date(first.year, first.month + 1, 1) - timedelta(days=1)
    return first, last


@dataclass
class TrendBucket:
    bucket_start: date
    bucket_end: date
    logged_days: int
    avg_nutrients: dict[str, float]


def bucket_day_totals(day_totals: dict[date, dict[str, float]], group_by: GroupBy) -> list[TrendBucket]:
    """Groups per-day nutrient totals (as produced by aggregate_nutrients
    for each logged day) into sorted week/month buckets, averaging each
    nutrient over the days logged within that bucket."""
    grouped: dict[tuple[date, date], list[dict[str, float]]] = {}
    for day, totals in day_totals.items():
        bounds = bucket_bounds(day, group_by)
        grouped.setdefault(bounds, []).append(totals)

    buckets = []
    for (bucket_start, bucket_end), days in grouped.items():
        sums: dict[str, float] = {}
        for totals in days:
            for key, amount in totals.items():
                sums[key] = sums.get(key, 0.0) + amount
        avg_nutrients = {key: total / len(days) for key, total in sums.items()}
        buckets.append(TrendBucket(bucket_start, bucket_end, len(days), avg_nutrients))

    buckets.sort(key=lambda b: b.bucket_start)
    return buckets
