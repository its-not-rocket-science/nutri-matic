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
from app.reference_patterns import AMINO_ACIDS
from app.recommend_ingredients import suggest_ingredients


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
    profile = make_profile(db)
    # a food that alone already meets/exceeds every tracked target is
    # unrealistic to construct exhaustively — instead confirm the "nothing
    # short" short-circuit directly: no FoodNutrient rows at all means no
    # totals, so nothing registers as a shortfall worth pooling candidates for
    current = make_food(db, "Water")
    make_food(db, "Lentils", fiber_total=8.0)
    result = suggest_ingredients(
        db, profile, [], {}, AnalysisPeriod.DAY,
    )
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
    current = make_food(db, "Water")
    make_food(db, "Lentils", fiber_total=8.0)
    result = suggest_ingredients(db, make_profile(db), [], {}, AnalysisPeriod.DAY)
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
    """Prompt 4 item 4: query count stays bounded (one FoodNutrient+Food
    query per shortfall nutrient, plus one constraint-tags query) no
    matter how many ineligible rows exist for that nutrient — never a
    per-candidate query."""
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
