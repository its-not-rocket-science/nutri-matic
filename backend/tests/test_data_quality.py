from app.data_quality import (
    DEFAULT_EXCLUDE_MULTIPLE,
    DEFAULT_REVIEW_MULTIPLE,
    assess_plausibility,
    implausibility_reason,
    is_implausible,
)


def test_flags_the_real_wal_mart_pie_crust_biotin_value():
    # biotin DRV (adult_female) is 30mcg; this branded food reports 576923mcg/100g
    reason = implausibility_reason("biotin", 576923)
    assert reason is not None
    assert "19,231x" in reason
    assert is_implausible("biotin", 576923)


def test_flags_the_actual_production_biotin_case_that_slipped_past_the_old_1000x_threshold():
    """Public-launch hardening prompt 3's exact reported bug: a branded
    food at 29,733 mcg biotin/100g (991x the 30mcg DRV) passed the old
    flat 1000x threshold — just under it. The nutrient-aware ceiling
    (biotin has no legitimately-concentrated whole-food source, so it
    gets the tight default rather than a loosened-for-iodine one) must
    exclude this, not let it slip through again."""
    reason = implausibility_reason("biotin", 29733)
    assert reason is not None
    assert is_implausible("biotin", 29733)


def test_does_not_flag_plausible_values_even_for_naturally_concentrated_foods():
    # cod liver oil vitamin D ~ 250mcg/100g against a 15mcg DRV -> ~17x, real and unremarkable
    assert implausibility_reason("vitamin_d", 250) is None
    assert not is_implausible("vitamin_d", 250)
    # kelp iodine ~2000mcg/100g against a 150mcg DRV -> ~13x, real and unremarkable
    assert implausibility_reason("iodine", 2000) is None


def test_iodine_gets_a_much_higher_ceiling_than_the_default_for_dried_seaweed():
    """Dried kelp/kombu can legitimately run to several thousand mcg
    iodine/100g — multiples that would be an obvious data error for
    almost any other nutrient are real for this one. Must not be
    excluded under iodine's own (much higher) ceiling, even though it
    would clear the generic DEFAULT_EXCLUDE_MULTIPLE many times over."""
    drv = 150  # approx adult iodine DRV used here
    dried_kelp_amount = drv * (DEFAULT_EXCLUDE_MULTIPLE + 50)  # far past the generic default
    assert implausibility_reason("iodine", dried_kelp_amount) is None


def test_boundary_is_exclusive_below_and_inclusive_at_the_exclude_threshold():
    drv = 30  # biotin — uses the default multiple, no override
    just_under = drv * DEFAULT_EXCLUDE_MULTIPLE - 1
    at_threshold = drv * DEFAULT_EXCLUDE_MULTIPLE
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


def test_review_tier_is_not_excluded_but_is_flagged_by_assess_plausibility():
    """Between the review and exclude multiples: not excluded from
    anything (is_implausible stays False — a real concentrated whole
    food like liver/brazil nuts must still count normally), but
    assess_plausibility (the audit report's own read) surfaces it."""
    drv = 30  # biotin
    review_amount = drv * (DEFAULT_REVIEW_MULTIPLE + 1)
    assert not is_implausible("biotin", review_amount)
    assessment = assess_plausibility("biotin", review_amount)
    assert assessment.disposition == "review"
    assert assessment.reason is not None


def test_ordinary_value_is_ok_disposition_with_no_reason():
    assessment = assess_plausibility("vitamin_d", 50)  # ~5x a 10mcg DRV — unremarkable
    assert assessment.disposition == "ok"
    assert assessment.reason is None
    assert assessment.multiple is not None


def test_excluded_disposition_matches_is_implausible():
    assessment = assess_plausibility("biotin", 576923)
    assert assessment.disposition == "excluded"
    assert is_implausible("biotin", 576923)
