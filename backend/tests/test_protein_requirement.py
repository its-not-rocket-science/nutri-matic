import pytest

from app.models import User
from app.protein_requirement import calculate_protein_target_g


def make_user(**kwargs):
    defaults = dict(
        email="test@example.com", password_hash="x",
        weight_kg=None, height_cm=None, birth_year=None, sex=None, activity_level=None,
        is_pregnant=False, is_lactating=False,
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_sedentary_baseline():
    user = make_user(weight_kg=70, birth_year=1990, sex="male", activity_level="sedentary")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(56.0)  # 0.8 * 70


def test_scales_with_activity_level():
    user = make_user(weight_kg=70, birth_year=1990, sex="male", activity_level="very_active")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(112.0)  # 1.6 * 70


def test_older_adult_floor_raises_sedentary_tier():
    # age 70, sedentary: 0.8g/kg tier is below the 1.0g/kg PROT-AGE floor
    user = make_user(weight_kg=70, birth_year=1956, sex="female", activity_level="sedentary")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(70.0)  # 1.0 * 70, not 0.8 * 70


def test_older_adult_floor_does_not_lower_a_higher_tier():
    # age 70, very_active: 1.6g/kg tier already exceeds the 1.0g/kg floor
    user = make_user(weight_kg=70, birth_year=1956, sex="female", activity_level="very_active")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(112.0)  # unchanged, 1.6 * 70


def test_younger_adult_unaffected_by_older_adult_floor():
    user = make_user(weight_kg=70, birth_year=1990, sex="male", activity_level="sedentary")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(56.0)  # still 0.8 * 70


def test_pregnancy_adds_flat_increment():
    base = make_user(weight_kg=60, birth_year=1990, sex="female", activity_level="sedentary")
    pregnant = make_user(
        weight_kg=60, birth_year=1990, sex="female", activity_level="sedentary", is_pregnant=True
    )
    assert calculate_protein_target_g(pregnant, current_year=2026) == pytest.approx(
        calculate_protein_target_g(base, current_year=2026) + 6
    )


def test_lactation_adds_flat_increment():
    base = make_user(weight_kg=60, birth_year=1990, sex="female", activity_level="sedentary")
    lactating = make_user(
        weight_kg=60, birth_year=1990, sex="female", activity_level="sedentary", is_lactating=True
    )
    assert calculate_protein_target_g(lactating, current_year=2026) == pytest.approx(
        calculate_protein_target_g(base, current_year=2026) + 11
    )


@pytest.mark.parametrize("missing_field", ["weight_kg", "birth_year", "activity_level"])
def test_returns_none_if_any_required_field_missing(missing_field):
    fields = dict(weight_kg=70, birth_year=1990, sex="male", activity_level="moderate")
    fields[missing_field] = None
    user = make_user(**fields)
    assert calculate_protein_target_g(user, current_year=2026) is None


def test_sex_not_required():
    """Unlike EER, the per-kg formula itself doesn't branch on sex — only
    pregnancy/lactation status does, and those aren't gated on sex being set."""
    user = make_user(weight_kg=70, birth_year=1990, sex=None, activity_level="moderate")
    assert calculate_protein_target_g(user, current_year=2026) == pytest.approx(84.0)  # 1.2 * 70
