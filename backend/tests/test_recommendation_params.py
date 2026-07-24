"""Tests for recommendation_params.py — hardening prompt 2's shared
date-range and priority-nutrients validation."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from app.recommendation_params import (
    MAX_DATE_RANGE_DAYS,
    MAX_PRIORITY_NUTRIENTS,
    parse_priority_nutrients,
    validate_date_range,
)


def test_valid_date_range_passes():
    validate_date_range(date(2026, 1, 1), date(2026, 1, 7))


def test_single_day_range_passes():
    validate_date_range(date(2026, 1, 1), date(2026, 1, 1))


def test_reversed_date_range_rejected():
    with pytest.raises(HTTPException) as exc_info:
        validate_date_range(date(2026, 1, 7), date(2026, 1, 1))
    assert exc_info.value.status_code == 422


def test_oversized_date_range_rejected():
    start = date(2026, 1, 1)
    end = start + timedelta(days=MAX_DATE_RANGE_DAYS + 10)
    with pytest.raises(HTTPException) as exc_info:
        validate_date_range(start, end)
    assert exc_info.value.status_code == 422


def test_date_range_at_exactly_the_maximum_passes():
    start = date(2026, 1, 1)
    end = start + timedelta(days=MAX_DATE_RANGE_DAYS - 1)  # inclusive span == MAX_DATE_RANGE_DAYS
    assert (end - start).days + 1 == MAX_DATE_RANGE_DAYS
    validate_date_range(start, end)


def test_priority_nutrients_none_returns_none():
    assert parse_priority_nutrients(None) is None


def test_priority_nutrients_empty_string_returns_none():
    assert parse_priority_nutrients("") is None
    assert parse_priority_nutrients("   ") is None


def test_priority_nutrients_trims_and_dedupes():
    result = parse_priority_nutrients(" iron , folate ,iron,  folate")
    assert result == {"iron", "folate"}


def test_priority_nutrients_rejects_unknown_key():
    with pytest.raises(HTTPException) as exc_info:
        parse_priority_nutrients("iron,not_a_real_nutrient")
    assert exc_info.value.status_code == 422
    assert "not_a_real_nutrient" in exc_info.value.detail


def test_priority_nutrients_rejects_too_many_keys():
    many = ",".join(f"fake_key_{i}" for i in range(MAX_PRIORITY_NUTRIENTS + 5))
    with pytest.raises(HTTPException) as exc_info:
        parse_priority_nutrients(many)
    assert exc_info.value.status_code == 422


def test_priority_nutrients_whitespace_only_tokens_ignored():
    result = parse_priority_nutrients("iron, , ,folate")
    assert result == {"iron", "folate"}
