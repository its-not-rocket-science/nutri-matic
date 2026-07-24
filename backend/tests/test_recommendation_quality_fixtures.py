"""Permanent, table-driven recommendation-quality regression suite —
prompt 13 of the nutrient-gap recommendation feature (see
docs/nutrient-gap-recommendations.md). Each `test_scenario_NN_*` function
below is one named scenario from the prompt, using a small deterministic
fixture catalogue built for that scenario alone.

Per the prompt's own instruction, these test ranking invariants and
explanation/structural fields (is a candidate suggested at all, does it
outrank another, is an excluded food ever present) rather than asserting
fragile exact floating-point scores — a scoring-weight tweak should not
break this file unless it actually breaks the invariant being protected.

Some of these invariants already have narrower unit tests elsewhere
(recommendation_scoring.py's own adversarial tests, recommend_pairs.py's
combined-excess test, etc.) — this file is the belt-and-suspenders
integration-level version, going through the real suggest_* entry points
end to end, and is where prompt 14 says future regression scenarios
should be added."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.aggregation import WeightedFood
from app.database import Base
from app.models import DietaryConstraint, Food, FoodNutrient, Profile, Recipe, RecipeIngredient, User
from app.nutrient_targets import AnalysisPeriod
from app.reference_patterns import AMINO_ACIDS
from app.recommend_ingredients import suggest_ingredients
from app.recommend_pairs import suggest_pairs
from app.recommend_recipes import suggest_recipes
from app.recommend_substitutions import suggest_substitutions


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db, email, is_system=False):
    user = User(email=email, password_hash="x", is_system=is_system)
    db.add(user)
    db.commit()
    return user


def make_profile(db, user_id=1, **kwargs):
    defaults = dict(
        user_id=user_id, name="Test", weight_kg=65.0, height_cm=168.0, birth_year=1994, sex="female",
        activity_level="moderate", is_pregnant=False, is_lactating=False, dietary_pattern=None, goal=None,
    )
    defaults.update(kwargs)
    profile = Profile(**defaults)
    db.add(profile)
    db.commit()
    return profile


def _aa(lysine: float = 100.0, others: float = 100.0) -> dict:
    return {aa: (lysine if aa == "lysine" else others) for aa in AMINO_ACIDS}


def make_food(db, name, protein=1.0, data_type="sr_legacy_food", amino_acids=None, **nutrients):
    food = Food(
        name=name, protein_g_per_100g=protein, amino_acids=amino_acids or dict.fromkeys(AMINO_ACIDS),
        data_type=data_type,
    )
    db.add(food)
    db.flush()
    for key, amount in nutrients.items():
        db.add(FoodNutrient(food_id=food.id, nutrient_key=key, amount_per_100g=amount))
    db.commit()
    return food


def make_recipe(db, user, name, servings, ingredients, **kwargs):
    recipe = Recipe(user_id=user.id, name=name, servings=servings, **kwargs)
    db.add(recipe)
    db.flush()
    for food, quantity_g in ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=quantity_g))
    db.commit()
    return recipe


def run_ingredients(db, profile, current, **kwargs):
    items = [WeightedFood(current, 100.0)]
    nutrients_by_food_id = {current.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current.id).all()}
    return suggest_ingredients(db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY, **kwargs)


# --- 1. Low fibre and folate: lentils/beans should outrank oil/cheese ------

def test_scenario_01_low_fibre_and_folate_favours_lentils_over_oil_or_cheese(db):
    current = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4, folate=5.0)
    make_food(db, "Lentils", fiber_total=8.0, folate=181.0, energy=116)
    make_food(db, "Olive oil", energy=884)  # no fibre/folate data at all — an oil has none to offer
    make_food(db, "Cheddar cheese", energy=400, fiber_total=0.0, folate=18.0)  # negligible fibre/folate

    profile = make_profile(db)
    result = run_ingredients(db, profile, current, priority_nutrient_keys={"fiber_total", "folate"})

    assert result.suggestions
    assert result.suggestions[0].food_name == "Lentils"
    # olive oil carries no fibre/folate data at all, so it's never even
    # pooled as a candidate for this gap
    assert all(s.food_name != "Olive oil" for s in result.suggestions)
    # cheese's negligible fibre/folate content must never outrank lentils'
    # real contribution, even if it's technically still a valid candidate
    by_name = {s.food_name: s for s in result.suggestions}
    if "Cheddar cheese" in by_name:
        assert by_name["Lentils"].score.total > by_name["Cheddar cheese"].score.total


# --- 2. Low calcium under a modest energy cap ------------------------------

def test_scenario_02_low_calcium_under_energy_cap_ranks_calcium_food_highly(db):
    current = make_food(db, "White rice, cooked", energy=130, calcium=2.0)
    make_food(db, "Yogurt, greek", calcium=110.0, energy=59)  # curated, low-energy, calcium-rich
    make_food(db, "Chocolate cake", calcium=50.0, energy=950)  # some calcium, but blows the cap

    profile = make_profile(db)
    result = run_ingredients(db, profile, current, priority_nutrient_keys={"calcium"}, max_additional_energy=100.0)

    assert result.suggestions
    assert result.suggestions[0].food_name == "Yogurt, greek"
    assert all(s.food_name != "Chocolate cake" for s in result.suggestions)


# --- 3. Iron gap with sodium near its limit --------------------------------

def test_scenario_03_iron_gap_with_sodium_near_limit_penalises_high_sodium_source(db):
    # sodium ceiling is 2400mg/day (flat) — already at 2200mg before any
    # candidate is added, so there's very little headroom left
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1, sodium=2200.0)
    make_food(db, "Kidney beans", iron=6.0, sodium=1.0, energy=127)  # low-sodium iron source
    make_food(db, "Salted iron cereal", iron=6.0, sodium=900.0, energy=110)  # high-sodium iron source

    profile = make_profile(db)
    result = run_ingredients(db, profile, current, priority_nutrient_keys={"iron"})

    by_name = {s.food_name: s for s in result.suggestions}
    if "Kidney beans" in by_name and "Salted iron cereal" in by_name:
        assert by_name["Kidney beans"].score.total > by_name["Salted iron cereal"].score.total
    else:
        # the high-sodium source may be rejected outright instead of merely
        # ranked lower — either way it must never win
        assert "Salted iron cereal" not in by_name or "Kidney beans" in by_name


# --- 4. Vegan profile: no animal products -----------------------------------

def test_scenario_04_vegan_profile_never_suggests_animal_products(db):
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1, protein=2.7)
    make_food(db, "Chicken breast, raw", protein=25.0, iron=5.0)
    make_food(db, "Lentils", fiber_total=1.0, iron=3.0, energy=116)

    profile = make_profile(db, dietary_pattern="vegan")
    result = run_ingredients(db, profile, current, priority_nutrient_keys={"iron"})

    assert all(s.food_name != "Chicken breast, raw" for s in result.suggestions)


# --- 5. Nut allergy: no nuts or nut-containing recipes ---------------------

def test_scenario_05_nut_allergy_excludes_nut_ingredients_and_nut_recipes(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    current = make_food(db, "White rice, cooked", energy=130, magnesium=5.0)
    almonds = make_food(db, "Almonds", magnesium=270.0, energy=579)
    lentils = make_food(db, "Lentils", magnesium=36.0, fiber_total=8.0, energy=116)
    make_recipe(db, system_user, "Almond Bake", 2, [(almonds, 100)], is_public=True, import_slug="almond_bake_test")

    profile = make_profile(db)
    db.add(DietaryConstraint(
        user_id=1, profile_id=profile.id, category="allergy", tag="tree_nut", severity="hard_exclude",
    ))
    db.commit()

    ingredient_result = run_ingredients(db, profile, current, priority_nutrient_keys={"magnesium"})
    assert all("Almond" not in s.food_name for s in ingredient_result.suggestions)

    items = [WeightedFood(current, 100.0)]
    nutrients_by_food_id = {current.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current.id).all()}
    recipe_result = suggest_recipes(
        db, profile, system_user, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        priority_nutrient_keys={"magnesium"},
    )
    assert all(s.recipe_name != "Almond Bake" for s in recipe_result.suggestions)


# --- 6. Energy fully allocated: substitution should be viable where -------
# --- addition isn't ---------------------------------------------------------

def test_scenario_06_energy_fully_allocated_substitution_works_where_addition_cannot(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    profile = make_profile(db, user_id=system_user.id)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    current_recipe = make_recipe(db, system_user, "Rice Bowl", 1, [(rice, 200)])
    replacement = make_recipe(
        db, system_user, "Lentil Bowl", 1, [(lentils, 200)],
        is_public=True, import_slug="lentil_bowl_test",
    )

    # zero energy headroom: addition mode must find nothing to add
    addition_result = run_ingredients(
        db, profile, rice, priority_nutrient_keys={"fiber_total"}, max_additional_energy=0.0,
    )
    assert addition_result.suggestions == []

    # substitution mode has no energy-headroom constraint of its own — it
    # can still find an improvement by swapping the whole meal instead
    substitution_result = suggest_substitutions(
        db, profile, system_user, [], current_recipe, 1.0, {}, AnalysisPeriod.DAY,
        priority_nutrient_keys={"fiber_total"},
    )
    assert any(s.replacement_recipe_name == "Lentil Bowl" for s in substitution_result.suggestions)


# --- 7. Protein quantity adequate, lysine quality weak ----------------------

def test_scenario_07_lysine_weak_protein_improved_by_complementary_recipe(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    profile = make_profile(db, user_id=system_user.id)
    # grain: plenty of protein quantity but low lysine (the amino acid
    # pattern's real limiting factor for cereals) — everything else high
    grain = make_food(
        db, "Wheat porridge", protein=10.0, energy=150, amino_acids=_aa(lysine=20.0),
    )
    # legume: high lysine, the classic real-world grain-legume complement
    legume = make_food(
        db, "Lentils, cooked", protein=9.0, fiber_total=8.0, energy=116, amino_acids=_aa(lysine=200.0),
    )
    # aggregate_nutrients only sums FoodNutrient rows, not Food.protein_g_
    # per_100g directly — a separate "protein" row is needed for the
    # protein_quality goal's shortfall detection to see any protein at all
    db.add(FoodNutrient(food_id=grain.id, nutrient_key="protein", amount_per_100g=10.0))
    db.add(FoodNutrient(food_id=legume.id, nutrient_key="protein", amount_per_100g=9.0))
    db.commit()
    make_recipe(
        db, system_user, "Lentil Side", 2, [(legume, 200)], is_public=True, import_slug="lentil_side_test",
    )

    items = [WeightedFood(grain, 300.0)]
    nutrients_by_food_id = {grain.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == grain.id).all()}
    result = suggest_recipes(
        db, profile, system_user, items, nutrients_by_food_id, AnalysisPeriod.DAY, goal="protein_quality",
    )

    suggestion = next((s for s in result.suggestions if s.recipe_name == "Lentil Side"), None)
    assert suggestion is not None
    assert suggestion.protein_added_g > 0


# --- 8. Missing candidate nutrient data reduces rank ------------------------

def test_scenario_08_missing_candidate_data_reduces_rank(db):
    current = make_food(db, "White rice, cooked", energy=130, iron=0.1, fiber_total=0.4)
    make_food(db, "Lentils", iron=6.0, fiber_total=8.0, energy=116)  # full data for both shortfalls
    make_food(db, "Kidney beans", iron=6.0)  # same iron, no fibre data at all

    profile = make_profile(db)
    result = run_ingredients(db, profile, current)

    by_name = {s.food_name: s for s in result.suggestions}
    assert "Lentils" in by_name
    if "Kidney beans" in by_name:
        assert by_name["Kidney beans"].data_coverage < by_name["Lentils"].data_coverage
        assert by_name["Lentils"].score.total > by_name["Kidney beans"].score.total


# --- 9. Category-proxy food ranks below an exact-data candidate -------------

def test_scenario_09_category_proxy_recipe_ranks_below_exact_data_recipe(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    profile = make_profile(db, user_id=system_user.id)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils_a = make_food(db, "Lentils A, cooked", fiber_total=8.0, energy=116)
    lentils_b = make_food(db, "Lentils B, cooked", fiber_total=8.0, energy=116)
    make_recipe(
        db, system_user, "Exact Lentil Soup", 2, [(lentils_a, 200)],
        is_public=True, import_slug="exact_lentil_test", match_coverage_lines=1.0, match_coverage_mass=1.0,
    )
    make_recipe(
        db, system_user, "Proxy Lentil Soup", 2, [(lentils_b, 200)],
        is_public=True, import_slug="proxy_lentil_test", match_coverage_lines=0.4, match_coverage_mass=0.4,
    )

    items = [WeightedFood(rice, 100.0)]
    nutrients_by_food_id = {rice.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == rice.id).all()}
    result = suggest_recipes(
        db, profile, system_user, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        priority_nutrient_keys={"fiber_total"}, max_suggestions=5,
    )

    by_name = {s.recipe_name: s for s in result.suggestions}
    if "Exact Lentil Soup" in by_name and "Proxy Lentil Soup" in by_name:
        assert by_name["Exact Lentil Soup"].score.total > by_name["Proxy Lentil Soup"].score.total


# --- 10. Extreme oversupply: capped benefit prevents score gaming ----------

def test_scenario_10_extreme_oversupply_does_not_win_purely_by_quantity(db):
    current = make_food(db, "White rice, cooked", energy=130, vitamin_c=2.0)
    make_food(db, "Orange", vitamin_c=53.0, energy=47)  # closes the gap sensibly
    make_food(db, "Vitamin C mega-source", vitamin_c=5000.0, energy=50)  # absurd oversupply

    profile = make_profile(db)
    result = run_ingredients(db, profile, current, priority_nutrient_keys={"vitamin_c"})

    by_name = {s.food_name: s for s in result.suggestions}
    if "Orange" in by_name and "Vitamin C mega-source" in by_name:
        # the mega-source must not score dramatically higher just for
        # supplying ~100x the nutrient once the target's already covered
        assert by_name["Vitamin C mega-source"].score.total < by_name["Orange"].score.total * 3


# --- 11. Two useful foods that combine badly -------------------------------

def test_scenario_11_pair_optimiser_penalises_combined_excess(db):
    current = make_food(db, "White rice, cooked", energy=130, sodium=1000.0, iron=0.1)
    salty_a = make_food(db, "Lentils", iron=3.0, sodium=1200.0, fiber_total=8.0, energy=116)
    salty_b = make_food(db, "Chickpeas", iron=3.0, sodium=1200.0, fiber_total=7.0, energy=120)

    profile = make_profile(db)
    items = [WeightedFood(current, 100.0)]
    nutrients_by_food_id = {current.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == current.id).all()}
    result = suggest_pairs(
        db, profile, items, nutrients_by_food_id, AnalysisPeriod.DAY, priority_nutrient_keys={"iron"},
    )
    # combining both high-sodium sources would push well past the 2400mg
    # sodium ceiling — the pair optimiser must never suggest that combination
    assert not any(
        {p.first.food_name, p.second.food_name} == {"Lentils", "Chickpeas"} for p in result.suggestions
    )


# --- 12. Duplicate recipes: diversity rule avoids near-identical results --

def test_scenario_12_duplicate_recipes_diversity_rule_deduplicates(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    profile = make_profile(db, user_id=system_user.id)
    rice = make_food(db, "White rice, cooked", energy=130, fiber_total=0.4)
    lentils = make_food(db, "Lentils", fiber_total=8.0, energy=116)
    make_recipe(
        db, system_user, "Lentil Soup Classic", 2, [(lentils, 200)],
        is_public=True, import_slug="lentil_classic_test",
    )
    make_recipe(
        db, system_user, "Lentil Soup Deluxe", 2, [(lentils, 200)],
        is_public=True, import_slug="lentil_deluxe_test",
    )

    items = [WeightedFood(rice, 100.0)]
    nutrients_by_food_id = {rice.id: db.query(FoodNutrient).filter(FoodNutrient.food_id == rice.id).all()}
    result = suggest_recipes(
        db, profile, system_user, items, nutrients_by_food_id, AnalysisPeriod.DAY,
        priority_nutrient_keys={"fiber_total"}, max_suggestions=5,
    )

    # both recipes share the same primary ingredient (lentils) — the
    # diversity rule must keep at most one of them
    lentil_soup_count = sum(1 for s in result.suggestions if s.recipe_name.startswith("Lentil Soup"))
    assert lentil_soup_count <= 1
