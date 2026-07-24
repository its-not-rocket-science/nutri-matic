"""Tests for recommendation_safety.py — prompt 11: age-based disable,
pregnancy/lactation warnings, and medical-constraint detection."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DietaryConstraint, Profile
from app.recommendation_safety import (
    MINIMUM_RECOMMENDATION_AGE,
    SafetyWarningCode,
    assess_eligibility,
    recipe_warnings,
)

CURRENT_YEAR = datetime.now().year


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_profile(db, **kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex="female",
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    profile = Profile(**defaults)
    db.add(profile)
    db.commit()
    return profile


def test_adult_profile_with_no_flags_is_enabled_with_baseline_warnings(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - 30)
    result = assess_eligibility(profile, db)
    assert result.enabled is True
    assert result.disabled_reason is None
    assert SafetyWarningCode.DATA_IS_ESTIMATE in result.warnings
    assert SafetyWarningCode.ABSORPTION_VARIES in result.warnings
    assert SafetyWarningCode.PREGNANCY_CONSERVATIVE not in result.warnings
    assert SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT not in result.warnings


def test_unknown_birth_year_does_not_disable(db):
    """No birth_year means age can't be computed — treated as "unknown",
    never assumed to be a child, since that would silently disable a
    real adult with an incomplete profile."""
    profile = make_profile(db, birth_year=None)
    result = assess_eligibility(profile, db)
    assert result.enabled is True


def test_under_minimum_age_disables_with_clear_reason(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - (MINIMUM_RECOMMENDATION_AGE - 1))
    result = assess_eligibility(profile, db)
    assert result.enabled is False
    assert result.disabled_reason is not None
    assert str(MINIMUM_RECOMMENDATION_AGE) in result.disabled_reason
    assert result.warnings == []


def test_exactly_minimum_age_is_enabled(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - MINIMUM_RECOMMENDATION_AGE)
    result = assess_eligibility(profile, db)
    assert result.enabled is True


def test_pregnant_profile_gets_pregnancy_warning(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - 30, is_pregnant=True)
    result = assess_eligibility(profile, db)
    assert result.enabled is True
    assert SafetyWarningCode.PREGNANCY_CONSERVATIVE in result.warnings
    assert SafetyWarningCode.LACTATION_CONSERVATIVE not in result.warnings


def test_lactating_profile_gets_lactation_warning(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - 30, is_lactating=True)
    result = assess_eligibility(profile, db)
    assert SafetyWarningCode.LACTATION_CONSERVATIVE in result.warnings


def test_medical_constraint_present_is_surfaced(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - 30)
    db.add(DietaryConstraint(user_id=1, profile_id=profile.id, category="medical", tag=None, note="renal diet"))
    db.commit()
    result = assess_eligibility(profile, db)
    assert result.enabled is True
    assert SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT in result.warnings


def test_non_medical_constraint_does_not_trigger_medical_warning(db):
    profile = make_profile(db, birth_year=CURRENT_YEAR - 30)
    db.add(DietaryConstraint(user_id=1, profile_id=profile.id, category="allergy", tag="peanut"))
    db.commit()
    result = assess_eligibility(profile, db)
    assert SafetyWarningCode.MEDICAL_CONSTRAINT_PRESENT not in result.warnings


def test_recipe_warnings_appends_without_dropping_existing():
    base = [SafetyWarningCode.DATA_IS_ESTIMATE]
    result = recipe_warnings(base)
    assert result == [SafetyWarningCode.DATA_IS_ESTIMATE, SafetyWarningCode.RECIPE_NUTRIENTS_VARY]
    assert base == [SafetyWarningCode.DATA_IS_ESTIMATE]  # not mutated in place
