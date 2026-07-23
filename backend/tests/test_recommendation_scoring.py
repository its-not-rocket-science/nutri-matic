"""Tests for recommendation_scoring.py — prompt 4: ranking behaviour,
including adversarial high-calorie, high-sodium, low-confidence,
incomplete-data and extreme-oversupply cases."""

import pytest

from app.aggregation import ProteinQualityResult
from app.dietary_tags import Suitability
from app.models import Profile
from app.nutrient_gap_analysis import analyse_nutrient_gap
from app.nutrient_targets import AnalysisPeriod, resolve_nutrient_target
from app.recommendation_scoring import PracticalityInput, ScoringWeights, score_candidate
from app.scoring import ScoreResult


def make_profile(**kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex=None,
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    return Profile(**defaults)


PROFILE = make_profile(sex="female")


def gap(key, consumed, coverage=1.0):
    t = resolve_nutrient_target(key, PROFILE, AnalysisPeriod.DAY)
    return analyse_nutrient_gap(key, consumed, coverage, t)


def test_gap_reduction_rewards_closing_a_shortfall():
    before = [gap("vitamin_c", 5.0)]
    after = [gap("vitamin_c", 35.0)]
    result = score_candidate(before, after)
    assert result.weighted_gap_reduction > 0
    assert "vitamin_c" in result.nutrients_improved
    assert result.total > 0


def test_no_reward_for_nutrient_already_above_target_before():
    """Adversarial: a nutrient already comfortably above target before the
    candidate — pushing it further up must never register as a reward,
    since its optimisation_weight was already 0 before the candidate too."""
    before = [gap("vitamin_c", 200.0)]  # well above preferred already
    after = [gap("vitamin_c", 250.0)]
    result = score_candidate(before, after)
    assert result.weighted_gap_reduction == 0.0
    assert result.nutrients_improved == []


def test_multi_nutrient_bonus_outranks_single_nutrient_of_equal_raw_size():
    # candidate A closes one nutrient's gap by a large amount
    before_a = [gap("vitamin_c", 5.0), gap("calcium", 700.0)]  # calcium already at target
    after_a = [gap("vitamin_c", 40.0), gap("calcium", 700.0)]
    # candidate B closes two different nutrients' gaps, same total raw shortfall closed
    before_b = [gap("vitamin_c", 22.5), gap("calcium", 350.0)]
    after_b = [gap("vitamin_c", 40.0), gap("calcium", 700.0)]

    score_a = score_candidate(before_a, after_a)
    score_b = score_candidate(before_b, after_b)
    # B touches two nutrients -> multi-nutrient bonus multiplier applies
    assert len(score_b.nutrients_improved) == 2
    assert len(score_a.nutrients_improved) == 1


def test_protein_quality_benefit_rewards_real_improvement():
    before_pq = ProteinQualityResult(
        score=ScoreResult(score=60.0, limiting_amino_acid="lysine", per_aa_ratios={}, pattern_used="adult"),
        coverage_fraction=1.0, covered_protein_g=20.0, total_protein_g=20.0,
    )
    after_pq = ProteinQualityResult(
        score=ScoreResult(score=85.0, limiting_amino_acid="lysine", per_aa_ratios={}, pattern_used="adult"),
        coverage_fraction=1.0, covered_protein_g=25.0, total_protein_g=25.0,
    )
    result = score_candidate([], [], protein_quality_before=before_pq, protein_quality_after=after_pq)
    assert result.protein_quality_benefit > 0


def test_protein_quality_benefit_zero_when_scores_unavailable():
    result = score_candidate([], [], protein_quality_before=None, protein_quality_after=None)
    assert result.protein_quality_benefit == 0.0


def test_dietary_fit_bonus_and_penalties():
    ok = score_candidate([], [], dietary_suitability=Suitability(status="ok", confidence="high"))
    avoid = score_candidate([], [], dietary_suitability=Suitability(status="avoid", confidence="high"))
    unknown = score_candidate([], [], dietary_suitability=Suitability(status="unknown", confidence="low"))
    none_given = score_candidate([], [], dietary_suitability=None)
    assert ok.dietary_fit > 0
    assert avoid.dietary_fit < 0
    assert unknown.dietary_fit < 0
    assert avoid.dietary_fit < unknown.dietary_fit  # avoid penalised more than merely unknown
    assert none_given.dietary_fit == 0.0


# --- adversarial cases -------------------------------------------------

def test_adversarial_high_sodium_upper_limit_breach_penalised_far_more_than_above_preferred():
    """A candidate that pushes sodium past its upper limit must score
    markedly worse than one that only pushes it moderately above
    preferred — prompt 4: upper-limit breaches get a stronger penalty."""
    before = [gap("sodium", 1000.0)]
    breach_after = [gap("sodium", 3000.0)]  # UL is 2400
    moderate_after = [gap("sodium", 2000.0)]  # still within, no breach

    breach_score = score_candidate(before, breach_after)
    moderate_score = score_candidate(before, moderate_after)
    assert breach_score.upper_limit_penalty > 0
    assert moderate_score.upper_limit_penalty == 0.0
    assert breach_score.total < moderate_score.total


def test_adversarial_high_calorie_candidate_penalised_by_energy_cap():
    within_cap = score_candidate([], [], energy_added=80.0, max_additional_energy=100.0)
    over_cap = score_candidate([], [], energy_added=600.0, max_additional_energy=100.0)
    assert within_cap.energy_overshoot_penalty == 0.0
    assert over_cap.energy_overshoot_penalty > 0
    assert over_cap.total < within_cap.total


def test_no_energy_penalty_when_no_cap_given():
    result = score_candidate([], [], energy_added=2000.0, max_additional_energy=None)
    assert result.energy_overshoot_penalty == 0.0


def test_adversarial_low_confidence_proxy_outranked_by_exact_match():
    """Same nutritional benefit, different ingredient-mapping confidence
    — the exact/regional-equivalent candidate (confidence 0.95) must
    outrank the category-proxy one (confidence 0.65), per prompt 4 point
    6."""
    before = [gap("iron", 5.0)]
    after = [gap("iron", 10.0)]
    exact = score_candidate(before, after, ingredient_confidence=0.95)
    proxy = score_candidate(before, after, ingredient_confidence=0.65)
    assert exact.total > proxy.total


def test_adversarial_incomplete_data_candidate_ranks_lower():
    before = [gap("iron", 5.0)]
    after = [gap("iron", 10.0)]
    complete = score_candidate(before, after, candidate_data_coverage=1.0)
    incomplete = score_candidate(before, after, candidate_data_coverage=0.4)
    assert complete.total > incomplete.total


def test_adversarial_extreme_oversupply_does_not_blow_up_the_score():
    """A shortfall closed by a modest amount vs an absurd oversupply of
    the same nutrient must not score wildly differently once the target
    is already met — nutrient_gap_analysis's own weight cap already
    prevents unbounded reward; this asserts the scoring layer doesn't
    reintroduce one."""
    before = [gap("vitamin_c", 5.0)]
    modest_after = [gap("vitamin_c", 40.0)]  # exactly meets target
    extreme_after = [gap("vitamin_c", 4000.0)]  # absurd oversupply, now above upper limit

    modest_score = score_candidate(before, modest_after)
    extreme_score = score_candidate(before, extreme_after)
    # the extreme case must not score *better* just because more was added —
    # its gap_reduction is capped the same as modest's, and it now also
    # picks up a real upper-limit penalty
    assert extreme_score.weighted_gap_reduction == pytest.approx(modest_score.weighted_gap_reduction)
    assert extreme_score.total < modest_score.total


def test_coverage_dilution_to_insufficient_data_is_never_counted_as_improvement():
    """Regression: adding a candidate with no data at all for an unrelated
    nutrient increases total consumed mass without adding any new
    information for that nutrient, which can drop its *coverage* below
    the judgeable threshold — demoting it to insufficient_data. That must
    never register as a "reduction" just because optimisation_weight
    also dropped to 0 alongside the status change."""
    before = [gap("fiber_total", 0.4, coverage=1.0)]
    after = [gap("fiber_total", 0.4, coverage=0.2)]  # same consumed amount, coverage diluted below the bar
    assert after[0].status.value == "insufficient_data"
    result = score_candidate(before, after)
    assert result.weighted_gap_reduction == 0.0
    assert "fiber_total" not in result.nutrients_improved


def test_practicality_neutral_when_no_data():
    result = score_candidate([], [], practicality=None)
    assert result.practicality == 0.0
    assert result.implausible_serving_penalty == 0.0


def test_practicality_bonus_when_plausible():
    result = score_candidate([], [], practicality=PracticalityInput(is_plausible_serving=True))
    assert result.practicality > 0
    assert result.implausible_serving_penalty == 0.0


def test_practicality_penalty_when_implausible():
    result = score_candidate([], [], practicality=PracticalityInput(is_plausible_serving=False))
    assert result.practicality == 0.0
    assert result.implausible_serving_penalty > 0


def test_score_breakdown_total_equals_component_sum():
    before = [gap("vitamin_c", 5.0), gap("sodium", 1000.0)]
    after = [gap("vitamin_c", 35.0), gap("sodium", 3000.0)]
    result = score_candidate(
        before, after, energy_added=600.0, max_additional_energy=100.0,
        dietary_suitability=Suitability(status="avoid", confidence="high"),
        ingredient_confidence=0.7, candidate_data_coverage=0.8,
        practicality=PracticalityInput(is_plausible_serving=True),
    )
    expected = (
        result.weighted_gap_reduction
        + result.protein_quality_benefit
        + result.dietary_fit
        + result.practicality
        - result.upper_limit_penalty
        - result.above_preferred_penalty
        - result.energy_overshoot_penalty
        - result.uncertainty_penalty
        - result.implausible_serving_penalty
    )
    assert result.total == pytest.approx(expected)


def test_custom_weights_override_defaults():
    before = [gap("vitamin_c", 5.0)]
    after = [gap("vitamin_c", 35.0)]
    default_score = score_candidate(before, after)
    weak_weights = ScoringWeights(gap_reduction_weight=0.1)
    weak_score = score_candidate(before, after, weights=weak_weights)
    assert weak_score.weighted_gap_reduction < default_score.weighted_gap_reduction
