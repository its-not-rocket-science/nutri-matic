from app.carbon_footprint import carbon_tier_confidence, carbon_tier_for_food


def test_ruminant_meat_is_very_high():
    assert carbon_tier_for_food("Beef, ground, 85% lean") == "very_high"
    assert carbon_tier_for_food("Lamb chop, raw") == "very_high"


def test_cheese_is_high():
    assert carbon_tier_for_food("Cheddar cheese, sharp") == "high"


def test_poultry_and_fish_are_medium():
    assert carbon_tier_for_food("Chicken breast, raw") == "medium"
    assert carbon_tier_for_food("Salmon, Atlantic, raw") == "medium"


def test_legumes_and_vegetables_are_low():
    assert carbon_tier_for_food("Lentils, raw") == "low"
    assert carbon_tier_for_food("Spinach, raw") == "low"


def test_unmatched_name_returns_none_not_a_guess():
    assert carbon_tier_for_food("Salt, table") is None


def test_mixed_name_prefers_highest_footprint_tier():
    """A dominant high-footprint ingredient shouldn't be masked by an
    incidental low-footprint word elsewhere in the name."""
    assert carbon_tier_for_food("Beef stock cube with vegetables") == "very_high"


def test_confidence_is_always_low_for_a_real_match():
    assert carbon_tier_confidence("very_high") == "low"
    assert carbon_tier_confidence("low") == "low"


def test_confidence_is_none_when_no_tier_matched():
    assert carbon_tier_confidence(None) is None
