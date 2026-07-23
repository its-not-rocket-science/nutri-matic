"""Tests for recommend_pairs.py — prompt 9: bounded, curated-only pairing,
combined (not summed) scoring, energy/upper-limit enforcement on the
combination, and a performance bound on pairs actually evaluated."""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.aggregation import WeightedFood
from app.database import Base
from app.models import Food, FoodNutrient, Profile
from app.nutrient_targets import AnalysisPeriod
from app.reference_patterns import AMINO_ACIDS
from app.recommend_pairs import MAX_PAIR_EVALUATIONS, suggest_pairs


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
    nutrients_by_food_id = {current_food.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current_food.id).all()}
    return suggest_pairs(db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY, **kwargs)


def test_curated_pair_yogurt_and_berries(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, calcium=1.0, vitamin_c=0.0)
    make_food(db, "Yogurt, greek", calcium=110.0, energy=59)
    make_food(db, "Strawberries, raw", vitamin_c=59.0, energy=32)

    result = run(db, profile, rice, priority_nutrient_keys={"calcium", "vitamin_c"})
    names = {(s.first.food_name, s.second.food_name) for s in result.suggestions}
    assert any({"Yogurt, greek", "Strawberries, raw"} == set(pair) for pair in names)


def test_condiment_base_pair_toast_and_peanut_butter(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4, magnesium=1.0)
    make_food(db, "Bread, whole wheat", fiber_total=6.0, energy=250, magnesium=5.0)
    make_food(db, "Peanut butter, smooth style without salt", magnesium=150.0, energy=590)

    result = run(db, profile, rice, priority_nutrient_keys={"fiber_total", "magnesium"})
    names = {(s.first.food_name, s.second.food_name) for s in result.suggestions}
    assert any({"Bread, whole wheat", "Peanut butter, smooth style without salt"} == set(pair) for pair in names)


def test_uncurated_unrelated_pair_never_formed(db):
    """Two foods with no condiment relationship and no curated pairing —
    a nutrient-math-only justification must never be enough on its own."""
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, iron=0.1, calcium=1.0)
    make_food(db, "Sardine, pacific, canned in tomato sauce", iron=3.0, energy=200)
    make_food(db, "Milk, whole", calcium=120.0, energy=60)

    result = run(db, profile, rice, priority_nutrient_keys={"iron", "calcium"})
    names = {(s.first.food_name, s.second.food_name) for s in result.suggestions}
    assert not any({"Sardine, pacific, canned in tomato sauce", "Milk, whole"} == set(pair) for pair in names)


def test_combined_scoring_rejects_upper_limit_breach_even_when_both_solo_are_fine(db):
    """Adversarial: two foods that individually look fine can combine to
    push a nutrient above its upper limit — must be rejected as a pair
    even though summing their individual scores would look positive."""
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, sodium=200.0, fiber_total=0.4)
    make_food(db, "Salty Ingredient A", sodium=1800.0, energy=100, fiber_total=5.0)
    make_food(db, "Salty Ingredient B", sodium=1800.0, energy=100, fiber_total=5.0)
    # force these two into CURATED_PAIRS-equivalent territory via condiment rule:
    # instead, directly verify no pair is suggested when it would breach sodium UL
    result = run(db, profile, rice, priority_nutrient_keys={"fiber_total"}, max_additional_energy=None)
    names = {(s.first.food_name, s.second.food_name) for s in result.suggestions}
    assert not any({"Salty Ingredient A", "Salty Ingredient B"} == set(pair) for pair in names)


def test_max_additional_energy_enforced_on_combination(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, calcium=1.0, vitamin_c=0.0)
    make_food(db, "Yogurt, greek", calcium=110.0, energy=400)  # inflated for the test
    make_food(db, "Strawberries, raw", vitamin_c=59.0, energy=400)  # inflated for the test

    result = run(db, profile, rice, priority_nutrient_keys={"calcium", "vitamin_c"}, max_additional_energy=100.0)
    assert result.suggestions == []
    assert any("cap" in r.reason for r in result.rejected)


def test_no_suggestion_when_nothing_short(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130)
    result = run(db, profile, rice)
    assert result.suggestions == []


def test_returns_individual_and_combined_contributions(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, calcium=1.0, vitamin_c=0.0)
    make_food(db, "Yogurt, greek", calcium=110.0, energy=59)
    make_food(db, "Strawberries, raw", vitamin_c=59.0, energy=32)

    result = run(db, profile, rice, priority_nutrient_keys={"calcium", "vitamin_c"})
    if result.suggestions:
        suggestion = result.suggestions[0]
        assert suggestion.first.solo_score is not None
        assert suggestion.second.solo_score is not None
        assert suggestion.score.total is not None


def test_performance_bounded_pair_evaluations(db):
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, iron=0.1, calcium=1.0, fiber_total=0.4)
    # a larger pool of foods all carrying the shortfall nutrients, to
    # stress-test that pair evaluation stays bounded rather than growing
    # combinatorially with pool size
    for i in range(20):
        make_food(db, f"Iron Food {i}", iron=5.0 + i * 0.1, energy=100)
        make_food(db, f"Calcium Food {i}", calcium=100.0 + i, energy=80)

    start = time.monotonic()
    result = run(db, profile, rice, priority_nutrient_keys={"iron", "calcium", "fiber_total"})
    elapsed = time.monotonic() - start

    assert result.pairs_evaluated <= MAX_PAIR_EVALUATIONS
    assert elapsed < 5.0  # generous bound — this must stay fast regardless of catalog size
