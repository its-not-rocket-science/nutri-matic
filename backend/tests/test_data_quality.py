import pytest

from app.data_quality import IMPLAUSIBLE_DRV_MULTIPLE, implausibility_reason, is_implausible


def test_flags_the_real_wal_mart_pie_crust_biotin_value():
    # biotin DRV (adult_female) is 30mcg; this branded food reports 576923mcg/100g
    reason = implausibility_reason("biotin", 576923)
    assert reason is not None
    assert "19,231x" in reason
    assert is_implausible("biotin", 576923)


def test_does_not_flag_plausible_values_even_for_naturally_concentrated_foods():
    # cod liver oil vitamin D ~ 250mcg/100g against a 15mcg DRV -> ~17x, real and unremarkable
    assert implausibility_reason("vitamin_d", 250) is None
    assert not is_implausible("vitamin_d", 250)
    # kelp iodine ~2000mcg/100g against a 150mcg DRV -> ~13x, real and unremarkable
    assert implausibility_reason("iodine", 2000) is None


def test_boundary_is_exclusive_below_and_inclusive_at_the_threshold():
    drv = 30  # biotin
    just_under = drv * IMPLAUSIBLE_DRV_MULTIPLE - 1
    at_threshold = drv * IMPLAUSIBLE_DRV_MULTIPLE
    assert implausibility_reason("biotin", just_under) is None
    assert implausibility_reason("biotin", at_threshold) is not None


def test_zero_or_negative_amount_is_never_flagged():
    assert implausibility_reason("biotin", 0) is None
    assert implausibility_reason("biotin", -5) is None


def test_nutrient_with_no_drv_is_never_flagged():
    # arachidonic_acid has no established DRV at all — nothing to compare against
    assert implausibility_reason("arachidonic_acid", 999999) is None


def test_unknown_nutrient_key_is_never_flagged():
    assert implausibility_reason("not_a_real_nutrient", 999999) is None


def test_reason_text_notes_exclusion_from_totals_and_suggestions():
    reason = implausibility_reason("biotin", 576923)
    assert "excluded" in reason.lower()
