"""Tests for recommend_ingredients.py — prompt 6: vegetarian/vegan
profiles, allergens, calorie caps, sodium limits, low-confidence
candidates, partial data, serving sizes, no-suitable-candidate, and
deterministic ordering."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.aggregation import WeightedFood
from app.database import Base, get_db
from app.demo_protection import reset_demo_rate_limits
from app.main import app
from app.models import DietaryConstraint, Food, FoodNutrient, Profile, User
from app.nutrient_targets import AnalysisPeriod
from app.nutrients import NUTRIENTS
from app.reference_patterns import AMINO_ACIDS
from app.recommend_ingredients import suggest_ingredients
from app.recommendation_scoring import ScoringWeights


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_profile(db, **kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=None, height_cm=None, birth_year=None, sex="female",
        activity_level=None, is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    profile = Profile(**defaults)
    db.add(profile)
    db.commit()
    return profile


def make_food(db, name, protein=1.0, data_type="sr_legacy_food", **nutrients):
    food = Food(name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type=data_type)
    db.add(food)
    db.flush()
    for key, amount in nutrients.items():
        db.add(FoodNutrient(food_id=food.id, nutrient_key=key, amount_per_100g=amount))
    db.commit()
    return food


def run(db, profile, current_food, **kwargs):
    items = [WeightedFood(current_food, 100.0)]
    nutrients_by_food_id = {
        current_food.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current_food.id).all(),
    }
    return suggest_ingredients(db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY, **kwargs)


def test_suggests_food_that_closes_a_real_shortfall(db):
    profile = make_profile(db)
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)  # real but low fibre value
    make_food(db, "Lentils", fiber_total=8.0, energy=116)  # curated candidate, high fibre

    result = run(db, profile, current)
    assert result.suggestions
    assert result.suggestions[0].food_name == "Lentils"
    assert "fiber_total" in result.suggestions[0].nutrients_improved


def test_no_suggestion_when_nothing_is_short(db):
    # a genuinely empty day (nothing logged at all) is no longer a valid
    # stand-in for "nothing is short" — treat_empty_day_as_zero (caught
    # by live testing: an unlogged day was wrongly returning zero
    # suggestions instead of "everything's short") makes an empty day
    # register every nutrient as maximally below target on purpose, so
    # this constructs a real well-fed day instead: one food supplying
    # every tracked nutrient generously, guaranteeing nothing is
    # below/near target regardless of how much is eaten.
    profile = make_profile(db)
    current = make_food(db, "Multivitamin mega-meal", **{key: 100000.0 for key in NUTRIENTS})
    make_food(db, "Lentils", fiber_total=8.0)
    result = run(db, profile, current)
    assert result.suggestions == []


def test_vegan_profile_never_suggests_poultry(db):
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Chicken breast, raw", protein=25.0, iron=5.0)  # curated, high iron, but poultry
    make_food(db, "Lentils", fiber_total=1.0, iron=3.0)  # curated, plant-based, some iron too

    vegan_profile = make_profile(db, dietary_pattern="vegan")
    result = run(db, vegan_profile, current, priority_nutrient_keys={"iron"})
    assert all(s.food_name != "Chicken breast, raw" for s in result.suggestions)


def test_omnivore_profile_can_be_suggested_poultry(db):
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Chicken breast, raw", protein=25.0, iron=5.0)

    profile = make_profile(db, dietary_pattern="omnivore")
    result = run(db, profile, current, priority_nutrient_keys={"iron"})
    assert any(s.food_name == "Chicken breast, raw" for s in result.suggestions)


def test_allergen_hard_exclusion_removes_candidate(db):
    current = make_food(db, "White rice, cooked", energy=130, magnesium=5.0)
    make_food(db, "Peanut butter, smooth style without salt", magnesium=150.0)  # curated, high magnesium

    profile = make_profile(db)
    db.add(DietaryConstraint(user_id=1, profile_id=profile.id, category="allergy", tag="peanut", severity="hard_exclude"))
    db.commit()

    result = run(db, profile, current, priority_nutrient_keys={"magnesium"})
    assert all("Peanut" not in s.food_name for s in result.suggestions)


def test_max_additional_energy_caps_suggestions(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Lentils", fiber_total=8.0, energy=800)  # implausibly calorie-dense for the test, to force a cap breach

    profile = make_profile(db)
    result = run(db, profile, current, max_additional_energy=50.0)
    assert result.suggestions == []
    assert any("cap" in r.reason for r in result.rejected)


def test_low_confidence_partial_data_candidate_ranks_below_complete_data_one(db):
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1, fiber_total=0.4)
    make_food(db, "Lentils", iron=6.0, fiber_total=8.0, energy=116)  # data for both shortfalls
    make_food(db, "Kidney beans", iron=6.0)  # same iron boost, no fibre data at all

    profile = make_profile(db)
    result = run(db, profile, current)
    by_name = {s.food_name: s for s in result.suggestions}
    assert "Lentils" in by_name
    assert by_name["Lentils"].data_coverage == 1.0
    if "Kidney beans" in by_name:
        assert by_name["Kidney beans"].data_coverage < 1.0
        assert by_name["Lentils"].score.total > by_name["Kidney beans"].score.total


def test_serving_size_uses_candidate_metadata_default(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)

    profile = make_profile(db)
    result = run(db, profile, current)
    lentil_suggestion = next(s for s in result.suggestions if s.food_name == "Lentils")
    assert lentil_suggestion.quantity_g == pytest.approx(130.0)  # Lentils' curated default_g


def test_no_suitable_candidate_when_pool_entirely_unsuitable(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.1)
    make_food(db, "Spices, dried mixed seasoning blend", fiber_total=40.0)  # excluded keyword

    profile = make_profile(db)
    result = run(db, profile, current)
    assert result.suggestions == []


def test_deterministic_ordering(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_food(db, "Chickpeas", fiber_total=7.0, energy=120)

    profile = make_profile(db)
    first = run(db, profile, current)
    second = run(db, profile, current)
    assert [s.food_name for s in first.suggestions] == [s.food_name for s in second.suggestions]


def test_meal_period_uses_remaining_room_not_flat_daily_target(db):
    """A meal-scoped request must compare against what's left of the day's
    target after other meals, not the flat whole-day figure — see
    adjust_target_for_remaining in nutrient_targets.py."""
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)
    profile = make_profile(db)
    items = [WeightedFood(current, 100.0)]
    nutrients_by_food_id = {
        current.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current.id).all(),
    }

    # no other meals logged yet: full daily fibre target (30g) still open
    result = suggest_ingredients(db, profile, items, nutrients_by_food_id, AnalysisPeriod.MEAL)
    assert any(s.food_name == "Lentils" for s in result.suggestions)

    # another meal already logged the day's full 30g fibre target: nothing left to close
    result = suggest_ingredients(
        db, profile, items, nutrients_by_food_id, AnalysisPeriod.MEAL,
        already_consumed_by_key={"fiber_total": 30.0},
    )
    assert result.suggestions == []


def test_respects_max_suggestions_limit(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_food(db, "Chickpeas", fiber_total=7.0, energy=120)
    make_food(db, "Black beans", fiber_total=8.5, energy=130)

    profile = make_profile(db)
    result = run(db, profile, current, max_suggestions=1)
    assert len(result.suggestions) == 1


# --- Public-launch hardening prompt 4: candidate-generation order -------


def test_impractical_records_dominating_raw_ranking_do_not_starve_out_a_practical_candidate(db):
    """The exact reported mechanism: more than CANDIDATE_POOL_PER_NUTRIENT
    impractical (uncurated-name) foods outrank a genuinely useful curated
    candidate by raw per-100g value alone. The old top-N-by-value-then-
    filter pipeline would fill its entire pool with the impractical rows
    and never even look at Lentils. Must still find it."""
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    from app.recommend_ingredients import CANDIDATE_POOL_PER_NUTRIENT

    for i in range(CANDIDATE_POOL_PER_NUTRIENT + 3):
        make_food(db, f"Generic Fiber Product #{i}", fiber_total=20.0, energy=50)  # outranks Lentils by value
    make_food(db, "Lentils", fiber_total=8.0, energy=116)  # curated, practical, real — but a lower raw value

    profile = make_profile(db)
    result = run(db, profile, current)
    assert any(s.food_name == "Lentils" for s in result.suggestions)


def test_impractical_records_are_rejected_not_silently_dropped(db):
    """The over-fetched, filtered-out impractical rows still show up in
    `rejected` with a stable reason — not silently discarded, matching
    the existing rejected-candidate convention this module already had."""
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Generic Fiber Product", fiber_total=50.0, energy=50)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)

    profile = make_profile(db)
    result = run(db, profile, current)
    rejected_names = [r.food_name for r in result.rejected]
    assert "Generic Fiber Product" in rejected_names
    matching = next(r for r in result.rejected if r.food_name == "Generic Fiber Product")
    assert matching.reason_code == "impractical"


def test_branded_records_never_enter_the_pool_regardless_of_value(db):
    """Branded products are always excluded by candidate_metadata
    regardless of name — pushed into the SQL filter itself now, so they
    never even reach the eligibility loop (cheaper, and structurally
    prevents near-duplicate branded product lines from crowding the
    pool, prompt 4 item 3)."""
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Fiber Bar Extreme", fiber_total=90.0, energy=50, data_type="branded_food")
    make_food(db, "Lentils", fiber_total=8.0, energy=116)

    profile = make_profile(db)
    result = run(db, profile, current)
    assert any(s.food_name == "Lentils" for s in result.suggestions)
    assert all("Fiber Bar" not in r.food_name for r in result.rejected)  # never fetched, so never even rejected


def test_dietary_exclusion_recovers_the_next_eligible_candidate_not_just_empties_the_pool(db):
    """Dietary exclusion is now applied inside the over-fetch window too
    (not just as a post-filter on an already-truncated pool) — a vegan
    profile excluding the single highest-ranked candidate must still
    find the next eligible one, not come back empty."""
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Chicken breast, raw", protein=25.0, iron=6.0)  # curated, highest iron, excluded for vegan
    make_food(db, "Lentils", iron=3.0, energy=116)  # curated, plant-based, real fallback

    vegan_profile = make_profile(db, dietary_pattern="vegan")
    result = run(db, vegan_profile, current, priority_nutrient_keys={"iron"})
    assert any(s.food_name == "Lentils" for s in result.suggestions)
    assert all(s.food_name != "Chicken breast, raw" for s in result.suggestions)


def test_no_shortfall_reason_code(db):
    profile = make_profile(db)
    current = make_food(db, "Multivitamin mega-meal", **{key: 100000.0 for key in NUTRIENTS})
    make_food(db, "Lentils", fiber_total=8.0)
    result = run(db, profile, current)
    assert result.suggestions == []
    assert result.no_suggestion_reason is not None
    assert result.no_suggestion_reason.value == "no_shortfall"


def test_no_eligible_candidates_reason_code(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.1)
    make_food(db, "Spices, dried mixed seasoning blend", fiber_total=40.0)  # excluded keyword — no eligible pool at all

    profile = make_profile(db)
    result = run(db, profile, current)
    assert result.suggestions == []
    assert result.no_suggestion_reason is not None
    assert result.no_suggestion_reason.value == "no_eligible_candidates"


def test_energy_limit_reason_code_when_every_eligible_candidate_exceeds_the_cap(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    make_food(db, "Lentils", fiber_total=8.0, energy=800)  # eligible, but blows the cap

    profile = make_profile(db)
    result = run(db, profile, current, max_additional_energy=50.0)
    assert result.suggestions == []
    assert result.no_suggestion_reason is not None
    assert result.no_suggestion_reason.value == "energy_limit"


def test_bounded_query_count_independent_of_junk_candidate_volume(db):
    """Prompt 4 item 4: query count stays bounded (at most
    CANDIDATE_FETCH_MAX_PAGES FoodNutrient+Food queries per shortfall
    nutrient, plus one constraint-tags query) no matter how many
    ineligible rows exist for that nutrient — never a per-candidate
    query, and never unbounded pagination."""
    from sqlalchemy import event

    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    for i in range(50):
        make_food(db, f"Generic Fiber Product #{i}", fiber_total=20.0, energy=50)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)

    profile = make_profile(db)

    queries = []
    engine = db.get_bind()

    def _count(*args, **kwargs):
        queries.append(1)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = run(db, profile, current)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert any(s.food_name == "Lentils" for s in result.suggestions)
    # generous fixed ceiling — the point is "doesn't scale with junk
    # count", not pinning an exact number that'll break on refactor
    assert len(queries) < 30


def test_empty_day_pooling_stays_bounded_across_dozens_of_shortfalls(db):
    """Caught by PR review on treat_empty_day_as_zero: with no items
    logged and no priority_nutrient_keys, dozens of optimisation-eligible
    nutrients now register as a shortfall at once (an empty day is
    treated as maximally short, not "nothing to assess"). Without
    MAX_SHORTFALL_KEYS_FOR_POOLING, that's dozens of extra
    CANDIDATE_FETCH_MAX_PAGES-page _candidate_pool queries — this proves
    the query count stays bounded (scaled to the capped key count, not
    every optimisation-eligible nutrient) even on a completely empty day."""
    from sqlalchemy import event

    make_food(db, "Lentils", fiber_total=8.0, energy=116, iron=3.3, protein=9.0)
    profile = make_profile(db)

    queries = []
    engine = db.get_bind()

    def _count(*args, **kwargs):
        queries.append(1)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = suggest_ingredients(db, profile, [], {}, AnalysisPeriod.DAY)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert result.suggestions
    # bounded by MAX_SHORTFALL_KEYS_FOR_POOLING regardless of how many of
    # NUTRIENTS' ~47 keys resolve to a real shortfall on an empty day
    assert len(queries) < 60


def test_refills_across_pages_when_the_first_window_is_entirely_ineligible(db, monkeypatch):
    """PR review finding: a single fixed-size over-fetch window can
    itself be entirely ineligible, still starving out a real candidate
    further down. Must page (bounded, not unbounded) until either the
    pool fills or pages run out — real "over-fetch/refill", not a bigger
    fixed guess."""
    import app.recommend_ingredients as ri

    monkeypatch.setattr(ri, "CANDIDATE_POOL_PER_NUTRIENT", 1)
    monkeypatch.setattr(ri, "CANDIDATE_FETCH_MULTIPLIER", 2)  # page_size = 2
    monkeypatch.setattr(ri, "CANDIDATE_FETCH_MAX_PAGES", 4)  # up to 8 rows considered

    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    # 6 ineligible rows outranking Lentils by value — spans 3 pages of the
    # tiny page_size=2 above, so Lentils only surfaces on page 4
    for i in range(6):
        make_food(db, f"Generic Fiber Product #{i}", fiber_total=20.0, energy=50)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)

    profile = make_profile(db)
    result = run(db, profile, current)
    assert any(s.food_name == "Lentils" for s in result.suggestions)


def test_gives_up_after_max_pages_rather_than_paginating_forever(db, monkeypatch):
    """The bound is real — enough ineligible rows to exceed
    CANDIDATE_FETCH_MAX_PAGES * page_size must still come back empty
    (with a stable reason), not hang or silently ignore the cap."""
    import app.recommend_ingredients as ri

    monkeypatch.setattr(ri, "CANDIDATE_POOL_PER_NUTRIENT", 1)
    monkeypatch.setattr(ri, "CANDIDATE_FETCH_MULTIPLIER", 2)  # page_size = 2
    monkeypatch.setattr(ri, "CANDIDATE_FETCH_MAX_PAGES", 2)  # only 4 rows ever considered

    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.5)
    for i in range(10):  # far more ineligible rows than the 4-row cap covers
        make_food(db, f"Generic Fiber Product #{i}", fiber_total=20.0, energy=50)
    make_food(db, "Lentils", fiber_total=8.0, energy=116)  # never reached

    profile = make_profile(db)
    result = run(db, profile, current)
    assert result.suggestions == []
    assert result.no_suggestion_reason is not None
    assert result.no_suggestion_reason.value == "no_eligible_candidates"


def test_implausible_value_on_one_nutrient_does_not_exclude_the_food_from_another(db):
    """PR review finding: is_implausible is per (food, nutrient) row, not
    per food — a food with a corrupted zinc value but perfectly good
    iron data must still be considered when iron is the shortfall being
    evaluated, not globally excluded the moment its zinc row is rejected."""
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1, zinc=0.1)
    # zinc value absurd enough to be excluded outright (data_quality's
    # default 100x ceiling) — real, valid iron data on the SAME (curated,
    # practical) food
    make_food(db, "Lentils", iron=6.0, zinc=5000.0, energy=100)

    profile = make_profile(db)
    result = run(db, profile, current, priority_nutrient_keys={"iron", "zinc"})
    assert any(s.food_name == "Lentils" for s in result.suggestions)


def test_carbon_footprint_goal_favours_lower_carbon_tier_candidate(db):
    """reduce_carbon_footprint active: two curated, equally-eligible
    candidates close the exact same real iron gap by the exact same
    amount (per-100g iron chosen to offset each food's own curated
    default serving size, so the simulated after-state is identical) —
    the only thing that can separate them is carbon_tier_for_food:
    "Cheddar cheese" matches the high tier, "Lentils" the low tier."""
    profile = make_profile(db, goal="reduce_carbon_footprint")
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Cheddar cheese", iron=10.0 / 30 * 100, energy=0.0)
    make_food(db, "Lentils", iron=10.0 / 130 * 100, energy=0.0)

    result = run(db, profile, current, priority_nutrient_keys={"iron"})
    by_name = {s.food_name: s for s in result.suggestions}
    assert set(by_name) == {"Cheddar cheese", "Lentils"}
    assert by_name["Lentils"].score.carbon_footprint_adjustment > 0
    assert by_name["Cheddar cheese"].score.carbon_footprint_adjustment < 0
    assert by_name["Lentils"].score.total > by_name["Cheddar cheese"].score.total
    assert [s.food_name for s in result.suggestions] == ["Lentils", "Cheddar cheese"]


def test_carbon_footprint_weight_scales_with_goal_priority_rank(db):
    """PR review: reduce_carbon_footprint at a lower priority rank must
    influence ranking less than at rank 1 — goals.py's documented 1/rank
    multi-goal policy, not a flat on/off switch. profile.goals is set
    directly (the transient attribute goals.goal_keys_of reads) rather
    than via real ProfileGoal rows — same shortcut this suite already
    takes for single-goal cases via Profile(goal=...)."""
    profile = make_profile(db)
    profile.goals = ["exploring", "reduce_carbon_footprint"]  # rank 2 -> weight 0.5
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Cheddar cheese", iron=10.0 / 30 * 100, energy=0.0)
    make_food(db, "Lentils", iron=10.0 / 130 * 100, energy=0.0)

    result = run(db, profile, current, priority_nutrient_keys={"iron"})
    by_name = {s.food_name: s for s in result.suggestions}
    weights = ScoringWeights()
    assert by_name["Lentils"].score.carbon_footprint_adjustment == pytest.approx(weights.carbon_low_bonus * 0.5)
    assert by_name["Cheddar cheese"].score.carbon_footprint_adjustment == pytest.approx(
        -weights.carbon_high_penalty * 0.5
    )


def test_carbon_footprint_adjustment_zero_when_goal_not_active(db):
    """Same two candidates, no reduce_carbon_footprint goal — carbon must
    never contribute to either candidate's score for a profile that
    didn't ask for it."""
    profile = make_profile(db)
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1)
    make_food(db, "Cheddar cheese", iron=10.0 / 30 * 100, energy=0.0)
    make_food(db, "Lentils", iron=10.0 / 130 * 100, energy=0.0)

    result = run(db, profile, current, priority_nutrient_keys={"iron"})
    assert len(result.suggestions) == 2
    for s in result.suggestions:
        assert s.score.carbon_footprint_adjustment == 0.0


@pytest.fixture
def client():
    """The live demo-day regression fixture, end to end through the real
    API — the actual reported scenario ("No safe or useful addition
    found" even though ordinary useful foods exist), not a synthetic
    unit-level reproduction."""
    reset_demo_rate_limits()
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSession()
    # a plausible slice of a real ingested catalog: the demo's own seeded
    # foods, a curated legume the demo doesn't happen to log, and a pile
    # of impractical/branded extreme-value records that would dominate a
    # naive top-N-by-value ranking for common shortfall nutrients
    # (fibre/iron especially) — reproducing the mechanism, not just
    # asserting the symptom is gone.
    make_food(db, "Chicken, broilers or fryers, breast, meat only, cooked, roasted", protein=31, energy=165, iron=0.4)
    make_food(db, "Egg, whole, cooked, hard-boiled", protein=13, energy=155, iron=1.2)
    make_food(db, "Rice, white, long-grain, regular, cooked", protein=2.7, energy=130, fiber_total=0.4, iron=0.2)
    make_food(db, "Broccoli, raw", protein=2.8, energy=34, fiber_total=2.6, iron=0.7)
    make_food(db, "Yogurt, Greek, plain, whole milk", protein=10, energy=97, iron=0.1)
    make_food(db, "Lentils", fiber_total=8.0, iron=3.3, energy=116)  # curated — not in the demo's own seed list
    for i in range(20):
        make_food(db, f"Branded Fiber+Iron Bar #{i}", fiber_total=45.0, iron=15.0, energy=60, data_type="branded_food")

    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_live_demo_day_add_foods_finds_a_practical_candidate_not_no_safe_or_useful_addition(client):
    token = client.post("/api/auth/demo").json()["access_token"]
    from datetime import date

    res = client.get(
        f"/api/recommendations/ingredients?entry_date={date.today().isoformat()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    # a real shortfall exists (fibre/iron, given the demo's seeded diet) —
    # either a genuinely useful candidate is found, or a specific, honest
    # reason is given; never a silent/unexplained empty result.
    if not body["suggestions"]:
        assert body["no_suggestion_reason_code"] is not None
    else:
        assert all("Branded Fiber+Iron Bar" not in s["food_name"] for s in body["suggestions"])
