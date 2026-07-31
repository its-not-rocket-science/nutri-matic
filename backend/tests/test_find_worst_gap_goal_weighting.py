"""Prompt 2.2: _find_worst_gap (routers/diary.py, shared by /gap-suggestions
and /meal-optimize) becomes goal-aware — a profile's active goals nudge
which nutrient counts as "the" gap, via goal_nutrient_priorities.py's
priority-weighted multipliers, rather than goals only ever gating an
unrelated calorie calculation or a cosmetic UI message."""

from app import schemas
from app.routers.diary import _find_worst_gap


def amount(key: str, percent_drv: float) -> schemas.NutrientAmountOut:
    return schemas.NutrientAmountOut(
        key=key, name=key, unit="mg", amount=1.0, adult_drv=100.0, percent_drv=percent_drv,
        drv_source=None, drv_confidence=None, drv_methodology_version="1",
    )


def test_no_goals_picks_plain_lowest_percent_drv():
    candidates = [amount("calcium", 40.0), amount("magnesium", 45.0)]
    worst = _find_worst_gap(candidates)
    assert worst.key == "calcium"


def test_goal_emphasized_nutrient_wins_a_close_tie():
    # magnesium (45%) is nominally less severe than calcium (40%), but
    # longevity emphasizes magnesium — the modest boost should be enough
    # to flip a close comparison like this one.
    candidates = [amount("calcium", 40.0), amount("magnesium", 45.0)]
    worst = _find_worst_gap(candidates, ["longevity"])
    assert worst.key == "magnesium"


def test_goal_boost_does_not_override_a_genuinely_severe_unrelated_gap():
    # calcium (10%) is a much more severe real gap than magnesium's
    # emphasized-but-mild 45% — the boost is deliberately modest (1.3x)
    # so it can't paper over a real physiological need this large.
    candidates = [amount("calcium", 10.0), amount("magnesium", 45.0)]
    worst = _find_worst_gap(candidates, ["longevity"])
    assert worst.key == "calcium"


def test_energy_is_still_always_excluded_regardless_of_goals():
    candidates = [amount("energy", 1.0), amount("iron", 90.0)]
    worst = _find_worst_gap(candidates, ["athletic_stamina"])
    assert worst.key == "iron"


def test_athletic_sub_goals_target_different_nutrients_for_the_same_data():
    """The prompt's explicit requirement: stamina/strength/power aren't
    synonyms — the same close-tie data should resolve differently
    depending on which one is active."""
    candidates = [amount("iron", 45.0), amount("calcium", 40.0)]
    # athletic_stamina emphasizes iron -> iron should win despite calcium's
    # nominally lower raw percentage
    assert _find_worst_gap(candidates, ["athletic_stamina"]).key == "iron"
    # athletic_strength does not emphasize iron at all -> plain lowest wins
    assert _find_worst_gap(candidates, ["athletic_strength"]).key == "calcium"


def test_no_matching_candidates_for_active_goals_falls_back_to_plain_lowest():
    candidates = [amount("vitamin_c", 20.0), amount("thiamin", 25.0)]
    worst = _find_worst_gap(candidates, ["athletic_power"])  # emphasizes neither
    assert worst.key == "vitamin_c"


def test_boost_never_promotes_an_adequate_nutrient_over_a_real_deficiency():
    """PR review: with an unconditional boost, calcium at 90% (a real
    deficiency) lost to magnesium at 110% (already adequate) once
    magnesium's 110 was divided by 1.3 to ~84.6 — exactly backwards. The
    boost must only ever apply while a nutrient is still below 100%."""
    candidates = [amount("calcium", 90.0), amount("magnesium", 110.0)]
    worst = _find_worst_gap(candidates, ["longevity"])  # emphasizes magnesium, not calcium
    assert worst.key == "calcium"


def test_boost_still_applies_normally_among_nutrients_all_below_target():
    # sanity check that the >=100% guard doesn't accidentally neuter the
    # boost for the ordinary case where every candidate is a real gap
    candidates = [amount("calcium", 40.0), amount("magnesium", 45.0)]
    worst = _find_worst_gap(candidates, ["longevity"])
    assert worst.key == "magnesium"
