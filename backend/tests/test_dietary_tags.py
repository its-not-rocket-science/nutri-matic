from app.dietary_tags import evaluate_food


def test_no_constraints_is_ok():
    result = evaluate_food("Chicken, breast, cooked", "sr_legacy_food", None, [])
    assert result.status == "ok"


def test_hard_exclude_matches_by_name_high_confidence_for_legacy_food():
    result = evaluate_food("Milk, whole, 3.25% milkfat", "sr_legacy_food", None, [("milk", "hard_exclude")])
    assert result.status == "excluded"
    assert result.confidence == "high"
    assert "Milk / dairy" in result.reasons


def test_avoid_severity_flags_without_excluding():
    result = evaluate_food("Peanut butter, smooth", "sr_legacy_food", None, [("peanut", "avoid")])
    assert result.status == "avoid"


def test_hard_exclude_wins_over_avoid_when_both_match():
    result = evaluate_food(
        "Peanut butter cookie with milk chocolate",
        "sr_legacy_food",
        None,
        [("peanut", "avoid"), ("milk", "hard_exclude")],
    )
    assert result.status == "excluded"


def test_branded_food_no_match_is_unknown_not_ok():
    result = evaluate_food("Grandma's Chocolate Chip Cookies", "branded_food", None, [("milk", "hard_exclude")])
    assert result.status == "unknown"
    assert result.confidence == "low"


def test_legacy_food_no_match_is_confidently_ok():
    result = evaluate_food("Onions, raw", "sr_legacy_food", None, [("milk", "hard_exclude")])
    assert result.status == "ok"
    assert result.confidence == "high"


def test_manually_entered_food_no_data_type_is_low_confidence():
    result = evaluate_food("Homemade granola", None, None, [("peanut", "hard_exclude")])
    assert result.status == "unknown"
    assert result.confidence == "low"


def test_vegan_pattern_excludes_dairy_and_meat():
    assert evaluate_food("Milk, whole", "sr_legacy_food", "vegan", []).status == "excluded"
    assert evaluate_food("Beef, ground, cooked", "sr_legacy_food", "vegan", []).status == "excluded"
    assert evaluate_food("Onions, raw", "sr_legacy_food", "vegan", []).status == "ok"


def test_vegetarian_pattern_allows_dairy_excludes_meat():
    result = evaluate_food("Milk, whole", "sr_legacy_food", "vegetarian", [])
    assert result.status == "ok"
    result = evaluate_food("Chicken, breast, cooked", "sr_legacy_food", "vegetarian", [])
    assert result.status == "excluded"


def test_pescatarian_allows_fish_excludes_meat():
    assert evaluate_food("Salmon, cooked", "sr_legacy_food", "pescatarian", []).status == "ok"
    assert evaluate_food("Pork, cooked", "sr_legacy_food", "pescatarian", []).status == "excluded"


def test_omnivore_and_flexitarian_exclude_nothing():
    assert evaluate_food("Pork, cooked", "sr_legacy_food", "omnivore", []).status == "ok"
    assert evaluate_food("Pork, cooked", "sr_legacy_food", "flexitarian", []).status == "ok"


def test_halal_excludes_pork_and_alcohol():
    from app.dietary_tags import RELIGIOUS_REQUIREMENTS

    tags = [(t, "hard_exclude") for t in RELIGIOUS_REQUIREMENTS["halal"]["excludes"]]
    assert evaluate_food("Pork, cooked", "sr_legacy_food", None, tags).status == "excluded"
    assert evaluate_food("Beer", "sr_legacy_food", None, tags).status == "excluded"
    assert evaluate_food("Chicken, breast, cooked", "sr_legacy_food", None, tags).status == "ok"


def test_nut_butter_is_not_flagged_as_dairy():
    """Regression: a bare "butter" keyword on the milk/dairy tag would
    false-positive on every nut butter ("Peanut butter, smooth", "Almond
    butter") — these are plant foods and must not be excluded for a vegan/
    dairy-allergic user."""
    result = evaluate_food("Peanut butter, smooth", "sr_legacy_food", "vegan", [])
    assert result.status == "ok"
    result = evaluate_food("Almond butter", "sr_legacy_food", None, [("milk", "hard_exclude")])
    assert result.status == "ok"


def test_dairy_butter_still_caught_via_dairy_keyword():
    result = evaluate_food("Butter oil, anhydrous", "sr_legacy_food", "vegan", [])
    assert result.status == "ok"  # honest gap: bare "Butter, salted" isn't caught by name alone anymore
    result = evaluate_food("Buttermilk, whole, cultured", "sr_legacy_food", "vegan", [])
    assert result.status == "excluded"


def test_unknown_tag_key_is_ignored_not_crash():
    result = evaluate_food("Onions, raw", "sr_legacy_food", None, [("not_a_real_tag", "hard_exclude")])
    assert result.status == "ok"
