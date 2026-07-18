import pytest

from app.energy import calculate_eer
from app.energy_goal import (
    CALORIE_FLOOR_FEMALE_KCAL,
    CALORIE_FLOOR_MALE_KCAL,
    DEFICIT_PERCENT_ADULT,
    DEFICIT_PERCENT_OLDER_ADULT,
    calculate_energy_target,
)
from app.models import User


def make_user(**kwargs):
    defaults = dict(
        email="test@example.com", password_hash="x",
        weight_kg=None, height_cm=None, birth_year=None, sex=None, activity_level=None,
        is_pregnant=False, is_lactating=False, goal=None,
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_no_goal_returns_plain_eer_unadjusted():
    user = make_user(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert target == pytest.approx(eer)
    assert adjusted is False


def test_unrelated_goal_returns_plain_eer_unadjusted():
    user = make_user(
        weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate",
        goal="protein_quality",
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert target == pytest.approx(eer)
    assert adjusted is False


def test_weight_loss_goal_applies_deficit():
    user = make_user(
        weight_kg=90, height_cm=180, birth_year=1990, sex="male", activity_level="moderate", goal="weight_loss",
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert adjusted is True
    assert target == pytest.approx(eer * (1 - DEFICIT_PERCENT_ADULT))


def test_visceral_fat_reduction_goal_applies_same_deficit_as_weight_loss():
    base = make_user(
        weight_kg=90, height_cm=180, birth_year=1990, sex="male", activity_level="moderate", goal="weight_loss",
    )
    visceral = make_user(
        weight_kg=90, height_cm=180, birth_year=1990, sex="male", activity_level="moderate",
        goal="visceral_fat_reduction",
    )
    target_base, _ = calculate_energy_target(base, current_year=2026)
    target_visceral, adjusted_visceral = calculate_energy_target(visceral, current_year=2026)
    assert adjusted_visceral is True
    assert target_visceral == pytest.approx(target_base)


def test_older_adult_gets_smaller_deficit():
    # age 70 in 2026 (born 1956)
    user = make_user(
        weight_kg=90, height_cm=180, birth_year=1956, sex="male", activity_level="moderate", goal="weight_loss",
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert adjusted is True
    assert target == pytest.approx(eer * (1 - DEFICIT_PERCENT_OLDER_ADULT))


def test_deficit_never_goes_below_female_floor():
    # small, low-EER woman where a 15% deficit would fall under the floor
    user = make_user(
        weight_kg=45, height_cm=150, birth_year=2000, sex="female", activity_level="sedentary", goal="weight_loss",
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert eer * (1 - DEFICIT_PERCENT_ADULT) < CALORIE_FLOOR_FEMALE_KCAL  # confirms the scenario is real
    assert target == pytest.approx(CALORIE_FLOOR_FEMALE_KCAL)
    assert adjusted is True  # still below plain EER, just floored rather than fully deficited


def test_deficit_never_goes_below_male_floor():
    user = make_user(
        weight_kg=50, height_cm=160, birth_year=2000, sex="male", activity_level="sedentary", goal="weight_loss",
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert eer * (1 - DEFICIT_PERCENT_ADULT) < CALORIE_FLOOR_MALE_KCAL
    assert target == pytest.approx(CALORIE_FLOOR_MALE_KCAL)
    assert adjusted is True


def test_pregnant_user_never_gets_a_deficit_regardless_of_goal():
    user = make_user(
        weight_kg=70, height_cm=170, birth_year=1995, sex="female", activity_level="moderate",
        goal="weight_loss", is_pregnant=True,
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert adjusted is False
    assert target == pytest.approx(eer)


def test_lactating_user_never_gets_a_deficit_regardless_of_goal():
    user = make_user(
        weight_kg=70, height_cm=170, birth_year=1995, sex="female", activity_level="moderate",
        goal="visceral_fat_reduction", is_lactating=True,
    )
    eer = calculate_eer(user, current_year=2026)
    target, adjusted = calculate_energy_target(user, current_year=2026)
    assert adjusted is False
    assert target == pytest.approx(eer)


def test_returns_none_when_eer_cannot_be_computed():
    user = make_user(weight_kg=None, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    assert calculate_energy_target(user, current_year=2026) is None
