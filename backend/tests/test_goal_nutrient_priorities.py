from app.goal_nutrient_priorities import GOAL_NUTRIENT_EMPHASIS, nutrient_priority_multipliers
from app.nutrients import NUTRIENTS


def test_no_goals_returns_no_multipliers():
    assert nutrient_priority_multipliers([]) == {}


def test_unrecognized_goal_is_ignored():
    assert nutrient_priority_multipliers(["exploring"]) == {}


def test_single_goal_applies_flat_boost_at_full_weight():
    result = nutrient_priority_multipliers(["longevity"])
    for nutrient_key, boost in GOAL_NUTRIENT_EMPHASIS["longevity"].items():
        assert result[nutrient_key] == boost  # rank 1 -> weight 1.0 -> full boost


def test_lower_priority_goal_gets_a_smaller_boost():
    result = nutrient_priority_multipliers(["exploring", "athletic_strength"])
    # athletic_strength is rank 2 here -> weight 0.5 -> half the raw boost
    raw_boost = GOAL_NUTRIENT_EMPHASIS["athletic_strength"]["protein"]
    assert result["protein"] == 1.0 + 0.5 * (raw_boost - 1.0)


def test_two_goals_emphasizing_the_same_nutrient_stack():
    result = nutrient_priority_multipliers(["longevity", "athletic_strength"])
    # both emphasize magnesium -> combined multiplier is higher than either alone
    longevity_only = nutrient_priority_multipliers(["longevity"])["magnesium"]
    assert result["magnesium"] > longevity_only


def test_athletic_sub_goals_have_distinct_not_identical_emphasis():
    """Prompt 2.2's explicit requirement: stamina/strength/power aren't
    synonyms and must score differently, not share one generic bucket."""
    stamina = set(GOAL_NUTRIENT_EMPHASIS["athletic_stamina"])
    strength = set(GOAL_NUTRIENT_EMPHASIS["athletic_strength"])
    power = set(GOAL_NUTRIENT_EMPHASIS["athletic_power"])
    assert stamina != strength
    assert strength != power
    assert stamina != power


def test_energy_is_never_emphasized():
    """_find_worst_gap excludes energy from candidates entirely (a
    calorie target isn't "a gap"), so an energy entry here would be
    silently inert — confirms none was left in by mistake."""
    for emphasis in GOAL_NUTRIENT_EMPHASIS.values():
        assert "energy" not in emphasis


def test_carbon_footprint_goal_has_no_nutrient_emphasis():
    """reduce_carbon_footprint is a food-level, not nutrient-level,
    signal (see carbon_footprint.py) — it must not appear here."""
    assert "reduce_carbon_footprint" not in GOAL_NUTRIENT_EMPHASIS


def test_blood_sugar_stability_goal_has_no_nutrient_emphasis():
    """Same reasoning as reduce_carbon_footprint — blood_sugar_stability
    is a food-level signal (see glycaemic_load.py), not a nutrient-gap
    one, so it must not appear here either."""
    assert "blood_sugar_stability" not in GOAL_NUTRIENT_EMPHASIS


def test_every_emphasized_nutrient_is_actually_optimisation_eligible():
    """PR review: epa/dha (no individual DRV — only a combined EPA+DHA
    target) and sodium (a maximum-guideline nutrient with no upward
    target) were in this dict but could never actually be selected by
    _find_worst_gap, which only ever compares optimisation-eligible
    candidates — an advertised boost that could never fire. Guards
    against that class of bug recurring for any future goal."""
    for goal, emphasis in GOAL_NUTRIENT_EMPHASIS.items():
        for nutrient_key in emphasis:
            nutrient_def = NUTRIENTS[nutrient_key]
            assert nutrient_def.optimisation_eligible, (
                f"{goal} emphasizes {nutrient_key}, which is never optimisation_eligible "
                "and so can never be selected by _find_worst_gap"
            )
