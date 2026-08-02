from app.glycaemic_load import glycaemic_tier_confidence, glycaemic_tier_for_food


def test_refined_high_sugar_foods_are_high():
    assert glycaemic_tier_for_food("Cornflakes, plain") == "high"
    assert glycaemic_tier_for_food("Watermelon, raw") == "high"


def test_dried_fruit_and_oats_are_medium():
    assert glycaemic_tier_for_food("Raisins") == "medium"
    assert glycaemic_tier_for_food("Oats, rolled") == "medium"


def test_legumes_vegetables_dairy_and_protein_are_low():
    assert glycaemic_tier_for_food("Lentils, raw") == "low"
    assert glycaemic_tier_for_food("Spinach, raw") == "low"
    assert glycaemic_tier_for_food("Cheddar cheese") == "low"
    assert glycaemic_tier_for_food("Chicken breast, raw") == "low"


def test_unmatched_name_returns_none_not_a_guess():
    assert glycaemic_tier_for_food("Salt, table") is None


def test_high_variability_staples_deliberately_untiered():
    """Bread, rice, potato, and banana are excluded entirely — their real
    GI depends on preparation/variety/ripeness far more than a food name
    alone can convey (see module docstring)."""
    assert glycaemic_tier_for_food("Bread, white, commercially prepared") is None
    assert glycaemic_tier_for_food("Rice, white, cooked") is None
    assert glycaemic_tier_for_food("Potato, baked, flesh and skin") is None
    assert glycaemic_tier_for_food("Bananas, raw") is None


def test_mixed_name_prefers_highest_gi_tier():
    assert glycaemic_tier_for_food("Honey-roasted almonds") == "medium"


def test_doughnut_does_not_inherit_low_tier_nut_substring():
    """Real collision caught by review: a bare "nut" keyword matched
    inside "doughnut" — a refined-sugar, deep-fried food with nothing to
    do with actual nuts. Every common nut is listed individually
    (almond/walnut/peanut/cashew/pistachio), so dropping the bare "nut"
    keyword loses no real coverage."""
    assert glycaemic_tier_for_food("Glazed doughnut") != "low"
    assert glycaemic_tier_for_food("Glazed doughnut") == "high"
    assert glycaemic_tier_for_food("Walnuts, raw") == "low"


def test_flavoured_soft_drink_does_not_inherit_whole_fruit_low_tier():
    """Real collision caught by review: "Soft drink, orange" matched the
    whole-fruit "orange" keyword and inherited its low tier — a
    sugar-sweetened soda has nothing in common with the fruit it's
    flavoured to taste like."""
    assert glycaemic_tier_for_food("Soft drink, orange") == "high"


def test_juice_does_not_inherit_whole_fruit_low_tier():
    """Real collision risk: "orange juice"/"apple juice" contain a LOW-tier
    whole-fruit keyword as a substring, but juice (no fibre, faster
    absorption) is consistently rated less favourably than the same fruit
    eaten whole — "juice" must win as a medium-tier match, checked before
    the low tier's fruit keywords."""
    assert glycaemic_tier_for_food("Orange juice") == "medium"
    assert glycaemic_tier_for_food("Apple juice, unsweetened") == "medium"


def test_confidence_is_always_low_for_a_real_match():
    assert glycaemic_tier_confidence("high") == "low"
    assert glycaemic_tier_confidence("low") == "low"


def test_confidence_is_none_when_no_tier_matched():
    assert glycaemic_tier_confidence(None) is None
