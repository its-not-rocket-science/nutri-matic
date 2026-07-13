import pytest

from app.energy import calculate_eer
from app.models import User


def make_user(**kwargs):
    defaults = dict(
        email="test@example.com", password_hash="x",
        weight_kg=None, height_cm=None, birth_year=None, sex=None, activity_level=None,
        is_pregnant=False, is_lactating=False,
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_calculate_eer_male():
    user = make_user(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    # BMR = 10*70 + 6.25*175 - 5*36 + 5 = 700 + 1093.75 - 180 + 5 = 1618.75
    # EER = 1618.75 * 1.55 = 2509.0625
    assert calculate_eer(user, current_year=2026) == pytest.approx(2509.0625)


def test_calculate_eer_female():
    user = make_user(weight_kg=60, height_cm=165, birth_year=1990, sex="female", activity_level="sedentary")
    # BMR = 10*60 + 6.25*165 - 5*36 - 161 = 600 + 1031.25 - 180 - 161 = 1290.25
    # EER = 1290.25 * 1.2 = 1548.3
    assert calculate_eer(user, current_year=2026) == pytest.approx(1548.3)


def test_calculate_eer_pregnant_adds_200():
    base = make_user(weight_kg=60, height_cm=165, birth_year=1990, sex="female", activity_level="sedentary")
    pregnant = make_user(
        weight_kg=60, height_cm=165, birth_year=1990, sex="female", activity_level="sedentary", is_pregnant=True
    )
    assert calculate_eer(pregnant, current_year=2026) == pytest.approx(
        calculate_eer(base, current_year=2026) + 200
    )


def test_calculate_eer_lactating_adds_500():
    base = make_user(weight_kg=60, height_cm=165, birth_year=1990, sex="female", activity_level="sedentary")
    lactating = make_user(
        weight_kg=60, height_cm=165, birth_year=1990, sex="female", activity_level="sedentary", is_lactating=True
    )
    assert calculate_eer(lactating, current_year=2026) == pytest.approx(
        calculate_eer(base, current_year=2026) + 500
    )


@pytest.mark.parametrize(
    "missing_field",
    ["weight_kg", "height_cm", "birth_year", "sex", "activity_level"],
)
def test_calculate_eer_returns_none_if_any_field_missing(missing_field):
    fields = dict(weight_kg=70, height_cm=175, birth_year=1990, sex="male", activity_level="moderate")
    fields[missing_field] = None
    user = make_user(**fields)
    assert calculate_eer(user, current_year=2026) is None
