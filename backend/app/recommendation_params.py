"""Shared query-parameter validation for `/api/recommendations/*` —
hardening prompt 2 (see docs/nutrient-gap-recommendations-hardening.md).

FastAPI/Pydantic's own `Query(..., ge=..., le=...)` constraints and
`Literal`/enum types already handle most of this (positive-integer ids,
bounded counts/energy, valid `source`/`meal`/enumerated values) directly
in each endpoint's signature — see `routers/recommendations.py`. This
module covers the two checks that don't fit a single-field `Query`
constraint: a date range's internal consistency (`start_date <=
end_date`, and a maximum span) and `priority_nutrients`' comma-separated
list (trim/dedupe/cap/validate against the real `NUTRIENTS` vocabulary).

Both raise before any database work — called at the top of each endpoint,
before `assess_eligibility` (which queries `DietaryConstraint`) or any
entry-loading query, so a malformed request never causes a DB round-trip
at all.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException

from .nutrients import NUTRIENTS

# A generous but real ceiling — a multi-day meal-plan range has no
# legitimate reason to span longer than a season, and an unbounded range
# would otherwise let a request force an arbitrarily large entry-loading
# query regardless of how tightly candidate retrieval itself is bounded.
MAX_DATE_RANGE_DAYS = 90

# Every optimisation-eligible nutrient this app tracks is comfortably
# under this — a cap exists to bound the request itself, not because a
# legitimate caller would ever approach it.
MAX_PRIORITY_NUTRIENTS = 20


def validate_date_range(start_date: date, end_date: date) -> None:
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_DATE_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"date range must not exceed {MAX_DATE_RANGE_DAYS} days (got {span_days})",
        )


def parse_priority_nutrients(raw: str | None) -> set[str] | None:
    """Trims whitespace, drops empty tokens, deduplicates, caps the
    count, and rejects any key this app doesn't actually track — an
    unknown key is almost always a typo or a stale client, and silently
    ignoring it would make the request quietly behave as "no priority"
    instead of surfacing the mistake."""
    if raw is None:
        return None
    keys = {token.strip() for token in raw.split(",") if token.strip()}
    if not keys:
        return None
    if len(keys) > MAX_PRIORITY_NUTRIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"priority_nutrients accepts at most {MAX_PRIORITY_NUTRIENTS} keys (got {len(keys)})",
        )
    unknown = sorted(keys - set(NUTRIENTS))
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown nutrient key(s): {', '.join(unknown)}",
        )
    return keys
