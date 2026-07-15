from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.entitlements import (
    FEATURE_ENTITLEMENTS,
    PLAN_FREE,
    PLAN_PAID,
    PLAN_TRIAL,
    effective_plan,
    require_feature,
    user_has_feature,
)
from app.models import User


def make_user(plan=PLAN_FREE, plan_expires_at=None):
    return User(id=1, email="a@example.com", password_hash="x", plan=plan, plan_expires_at=plan_expires_at)


def test_effective_plan_free_user():
    assert effective_plan(make_user(PLAN_FREE)) == PLAN_FREE


def test_effective_plan_paid_user():
    assert effective_plan(make_user(PLAN_PAID)) == PLAN_PAID


def test_effective_plan_active_trial():
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    assert effective_plan(make_user(PLAN_TRIAL, plan_expires_at=tomorrow)) == PLAN_TRIAL


def test_effective_plan_expired_trial_reads_as_free():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    assert effective_plan(make_user(PLAN_TRIAL, plan_expires_at=yesterday)) == PLAN_FREE


def test_effective_plan_trial_with_no_expiry_stays_trial():
    assert effective_plan(make_user(PLAN_TRIAL, plan_expires_at=None)) == PLAN_TRIAL


def test_feature_with_no_entitlements_entry_is_available_to_everyone():
    assert "not_a_real_feature_key" not in FEATURE_ENTITLEMENTS
    assert user_has_feature(make_user(PLAN_FREE), "not_a_real_feature_key") is True


def test_feature_gated_to_paid_only(monkeypatch):
    monkeypatch.setitem(FEATURE_ENTITLEMENTS, "some_paid_feature", {PLAN_PAID})
    assert user_has_feature(make_user(PLAN_PAID), "some_paid_feature") is True
    assert user_has_feature(make_user(PLAN_FREE), "some_paid_feature") is False


def test_feature_gate_respects_expired_trial(monkeypatch):
    monkeypatch.setitem(FEATURE_ENTITLEMENTS, "some_paid_feature", {PLAN_PAID, PLAN_TRIAL})
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    expired_trial_user = make_user(PLAN_TRIAL, plan_expires_at=yesterday)
    assert user_has_feature(expired_trial_user, "some_paid_feature") is False


def test_require_feature_raises_403_when_not_entitled(monkeypatch):
    monkeypatch.setitem(FEATURE_ENTITLEMENTS, "some_paid_feature", {PLAN_PAID})
    check = require_feature("some_paid_feature")
    with pytest.raises(HTTPException) as exc_info:
        check(current_user=make_user(PLAN_FREE))
    assert exc_info.value.status_code == 403


def test_require_feature_passes_through_user_when_entitled(monkeypatch):
    monkeypatch.setitem(FEATURE_ENTITLEMENTS, "some_paid_feature", {PLAN_PAID})
    check = require_feature("some_paid_feature")
    user = make_user(PLAN_PAID)
    assert check(current_user=user) is user
