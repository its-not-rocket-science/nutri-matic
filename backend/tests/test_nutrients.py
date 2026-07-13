from app.nutrients import resolve_drv


def test_resolve_drv_no_profile_defaults_to_adult_female():
    assert resolve_drv("vitamin_a", profile=None) == 600


def test_resolve_drv_adult_male():
    assert resolve_drv("vitamin_a", profile=("male", False, False)) == 700


def test_resolve_drv_adult_female():
    assert resolve_drv("vitamin_a", profile=("female", False, False)) == 600


def test_resolve_drv_pregnant():
    assert resolve_drv("folate", profile=("female", True, False)) == 300


def test_resolve_drv_lactating():
    assert resolve_drv("folate", profile=("female", False, True)) == 260


def test_resolve_drv_lactating_takes_priority_over_pregnant():
    assert resolve_drv("calcium", profile=("female", True, True)) == 1250


def test_resolve_drv_falls_back_to_female_when_no_increment_documented():
    # niacin has no confirmed pregnancy/lactation increment
    assert resolve_drv("niacin", profile=("female", True, False)) == 12
    assert resolve_drv("niacin", profile=("female", False, True)) == 12


def test_resolve_drv_returns_none_for_nutrients_with_no_drv():
    assert resolve_drv("beta_carotene", profile=None) is None
    assert resolve_drv("epa", profile=("male", False, False)) is None


def test_resolve_drv_unknown_nutrient_returns_none():
    assert resolve_drv("not_a_real_nutrient", profile=None) is None
