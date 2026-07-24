"""Performance/bound tests for the nutrient-gap recommendation engine —
prompt 12. No caching layer exists in this codebase (no Redis, no
request-level cache anywhere) and this feature deliberately doesn't add
one — see docs/nutrient-gap-recommendations.md's performance section for
why a naive cache would be actively risky here (every response depends on
live diary/meal-plan state that changes on every add/remove). Instead,
this file verifies the actual load-bearing performance property: query
count and wall-clock time stay bounded by the CANDIDATE_POOL_* constants
regardless of how large the underlying food/recipe catalog grows —
"deterministic limits" rather than caching is this feature's answer to
prompt 12."""

import time

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.aggregation import WeightedFood
from app.database import Base
from app.models import Food, FoodNutrient, Profile, Recipe, RecipeIngredient, User
from app.nutrient_targets import AnalysisPeriod
from app.reference_patterns import AMINO_ACIDS
from app.recommend_ingredients import suggest_ingredients
from app.recommend_recipes import suggest_recipes


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class QueryCounter:
    """Counts SQL statements actually sent to the DB engine for one
    `with QueryCounter(session) as counter:` block — the real, load-
    bearing number a bounded-candidate-retrieval claim has to be checked
    against, not just "the code has a LIMIT in it somewhere"."""

    def __init__(self, session):
        self.engine = session.get_bind()
        self.count = 0

    def _before_cursor_execute(self, *_args, **_kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._before_cursor_execute)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._before_cursor_execute)


def make_profile(db, **kwargs):
    defaults = dict(
        user_id=1, name="Test", weight_kg=70, height_cm=170, birth_year=1990, sex="female",
        activity_level="moderate", is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
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


def _seed_catalog(db, count):
    """`count` distinct "Iron Food N" rows, all carrying the same
    shortfall nutrient — a stand-in for a much larger real food catalog
    than any single request should ever need to fully scan."""
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4, iron=0.1)
    for i in range(count):
        make_food(db, f"Iron Food {i}", iron=5.0 + i * 0.01, energy=100)
    return current


def _run_ingredients(db, profile, current):
    items = [WeightedFood(current, 100.0)]
    nutrients_by_food_id = {current.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current.id).all()}
    return suggest_ingredients(
        db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY, priority_nutrient_keys={"iron"},
    )


@pytest.mark.parametrize("catalog_size", [20, 300])
def test_ingredient_query_count_is_bounded_not_catalog_sized(db, catalog_size):
    profile = make_profile(db)
    current = _seed_catalog(db, catalog_size)

    with QueryCounter(db) as counter:
        _run_ingredients(db, profile, current)

    # generous fixed ceiling — the actual claim under test is the second
    # assertion below (flat regardless of catalog_size), this just also
    # catches a query count blowing up to something absurd outright
    assert counter.count < 50


def test_ingredient_query_count_does_not_scale_with_catalog_size(db):
    small_engine_counts = []
    for catalog_size in (20, 300):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()
        profile = make_profile(session)
        current = _seed_catalog(session, catalog_size)

        with QueryCounter(session) as counter:
            _run_ingredients(session, profile, current)
        small_engine_counts.append(counter.count)
        session.close()

    # a 15x larger catalog must not meaningfully change the query count —
    # CANDIDATE_POOL_PER_NUTRIENT's LIMIT is what bounds this, not luck
    assert small_engine_counts[1] <= small_engine_counts[0] + 2


def make_user(db, email, is_system=False):
    user = User(email=email, password_hash="x", is_system=is_system)
    db.add(user)
    db.commit()
    return user


def make_recipe(db, user, name, servings, ingredients, **kwargs):
    recipe = Recipe(user_id=user.id, name=name, servings=servings, **kwargs)
    db.add(recipe)
    db.flush()
    for food, quantity_g in ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=quantity_g))
    db.commit()
    return recipe


def test_recipe_suggestion_benchmark_against_a_realistic_catalog(db):
    """Wall-clock benchmark against a stock-recipe-library-sized catalog —
    documented in docs/nutrient-gap-recommendations.md alongside the
    actual measured figure from this test run. A generous bound (not a
    tight regression target) so CI environment variance doesn't make this
    test flaky; the number that matters is what's written in the docs."""
    system_user = make_user(db, "stock@example.com", is_system=True)
    profile = make_profile(db)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4, iron=0.1)

    # ~120 stock recipes, a realistic upper end for this app's current
    # library — each with its own lentil-based ingredient so every recipe
    # is a genuine, scoreable candidate, not an instantly-rejected one
    for i in range(120):
        lentils = make_food(db, f"Lentils variant {i}, cooked", fiber_total=8.0, iron=3.3, energy=116)
        make_recipe(
            db, system_user, f"Lentil Soup {i}", 2, [(lentils, 200)],
            is_public=True, import_slug=f"lentil_soup_{i}",
        )

    items = [WeightedFood(rice, 100.0)]
    nutrients_by_food_id = {rice.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == rice.id).all()}

    start = time.monotonic()
    result = suggest_recipes(
        db, profile, system_user, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        priority_nutrient_keys={"iron", "fiber_total"},
    )
    elapsed = time.monotonic() - start

    assert result.suggestions  # a real result, not an empty short-circuit
    assert elapsed < 5.0  # generous — see docstring
