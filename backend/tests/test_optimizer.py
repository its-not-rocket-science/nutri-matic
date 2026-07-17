import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.aggregation import WeightedFood
from app.database import Base
from app.models import Food, FoodNutrient, Recipe
from app.optimizer import suggest_meal_optimizations
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_food(db, id_, name, iron, energy=130.0):
    food = Food(id=id_, name=name, protein_g_per_100g=5, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add(food)
    db.flush()
    db.add(FoodNutrient(food_id=id_, nutrient_key="iron", amount_per_100g=iron))
    db.add(FoodNutrient(food_id=id_, nutrient_key="energy", amount_per_100g=energy))
    return food


def test_suggests_add_and_swap_ranked_by_improvement(db):
    rice_white = make_food(db, 1, "Rice, white, cooked", iron=1.0, energy=130)
    rice_brown = make_food(db, 3, "Rice, brown, cooked", iron=2.0, energy=130)  # same-family swap, no calorie cost
    spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)  # add candidate
    db.commit()

    by_food_id = {
        1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all(),
        2: db.query(FoodNutrient).filter(FoodNutrient.food_id == 2).all(),
    }

    swappable_items = [WeightedFood(rice_white, 100)]
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=swappable_items,
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[spinach],
        limit=5,
    )

    assert len(suggestions) == 2
    # swap (rice white -> brown): 1mg -> 2mg iron = +10 percentage points, ranked first
    swap = suggestions[0]
    assert swap.action == "swap"
    assert swap.food_id == rice_brown.id
    assert swap.replaces_food_id == rice_white.id
    assert swap.before_percent_drv == pytest.approx(10.0)
    assert swap.after_percent_drv == pytest.approx(20.0)
    assert swap.improvement == pytest.approx(10.0)
    assert swap.calories_added == pytest.approx(0.0)  # same energy, same quantity
    assert swap.improvement_per_100kcal is None  # no calorie cost to rank by

    # add 30g spinach: +0.9mg iron = +9 percentage points, ranked second
    add = suggestions[1]
    assert add.action == "add"
    assert add.food_id == spinach.id
    assert add.quantity_g == pytest.approx(30.0)
    assert add.improvement == pytest.approx(9.0)
    assert add.calories_added == pytest.approx(6.0)  # 20kcal/100g * 30g/100
    assert add.improvement_per_100kcal == pytest.approx(9.0 / (6.0 / 100))


def test_no_add_suggestion_for_zero_iron_candidate(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=5.0)
    zero_iron_candidate = make_food(db, 2, "Water", iron=0.0)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[zero_iron_candidate],
        limit=5,
    )
    assert suggestions == []


def test_no_swap_suggestion_for_worse_same_family_candidate(db):
    rice_white = make_food(db, 1, "Rice, white, cooked", iron=5.0)
    make_food(db, 3, "Rice, instant, cooked", iron=1.0)  # same family, but worse
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice_white, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[],
        limit=5,
    )
    assert suggestions == []


def test_suggestion_has_no_cost_when_price_unknown(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[spinach],
        limit=5,
    )
    assert len(suggestions) == 1
    assert suggestions[0].estimated_cost is None  # no prices_by_food_id given — never fabricated


def test_suggestion_has_real_cost_when_price_known(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[spinach],
        limit=5,
        prices_by_food_id={2: 0.50},  # 50p/100g
    )
    assert len(suggestions) == 1
    # ADD_TRIAL_QUANTITY_G = 30g -> 0.50 * 30/100 = 0.15
    assert suggestions[0].estimated_cost == pytest.approx(0.15)


def test_max_additional_cost_excludes_suggestions_over_budget(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    expensive_spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[expensive_spinach],
        limit=5,
        prices_by_food_id={2: 10.0},  # 30g -> 3.00, well over budget
        max_additional_cost=1.0,
    )
    assert suggestions == []


def test_max_additional_cost_keeps_unpriced_suggestions(db):
    """A budget constraint shouldn't silently exclude nutritionally-good
    suggestions just because this user hasn't priced that food yet."""
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    unpriced_spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[unpriced_spinach],
        limit=5,
        prices_by_food_id={},  # nothing priced
        max_additional_cost=0.01,
    )
    assert len(suggestions) == 1
    assert suggestions[0].estimated_cost is None


def test_rationale_mentions_target_nutrient_name(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    spinach = make_food(db, 2, "Spinach, raw", iron=3.0, energy=20)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[spinach],
        limit=5,
        target_nutrient_name="Iron",
    )
    assert "Iron" in suggestions[0].rationale
    assert "Spinach, raw" in suggestions[0].rationale


def test_no_suggestions_when_target_drv_is_zero(db):
    """A worst-gap nutrient with no established DRV (adult_drv is None,
    router falls back to 0.0) must not divide by zero — _simulate_percent_drv
    short-circuits to 0.0% before/after, so nothing can show "improvement"."""
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    rice_brown = make_food(db, 2, "Rice, brown, cooked", iron=2.0)
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=0.0,
        gap_candidates=[],
        limit=5,
    )
    assert suggestions == []


def test_swap_only_matches_same_family(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    quinoa = make_food(db, 2, "Quinoa, cooked", iron=5.0)  # not same family as "Rice" — shouldn't be suggested
    db.commit()

    by_food_id = {1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all()}
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[],
        limit=5,
    )
    assert all(s.food_id != quinoa.id for s in suggestions)
    assert suggestions == []  # no same-family "Rice, ..." candidates exist besides itself


def test_other_meals_items_unaffected_by_swap(db):
    """A swap should only touch the target meal's item, not other meals'
    contribution to the day total — verified by giving another meal a
    fixed iron amount that must appear unchanged in the before/after."""
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    rice_brown = make_food(db, 3, "Rice, brown, cooked", iron=2.0)
    other_meal_food = make_food(db, 4, "Beef, cooked", iron=4.0)
    db.commit()

    by_food_id = {
        1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all(),
        4: db.query(FoodNutrient).filter(FoodNutrient.food_id == 4).all(),
    }
    other_items = [WeightedFood(other_meal_food, 100)]  # +4mg iron, present in both before and after
    swappable_items = [WeightedFood(rice, 100)]

    suggestions = suggest_meal_optimizations(
        db, other_items, swappable_items, by_food_id, "iron", 10.0, gap_candidates=[], limit=5
    )

    swap = next(s for s in suggestions if s.food_id == rice_brown.id)
    # before: 4 (other meal) + 1 (rice white) = 5mg -> 50%; after: 4 + 2 = 6mg -> 60%
    assert swap.before_percent_drv == pytest.approx(50.0)
    assert swap.after_percent_drv == pytest.approx(60.0)


def test_suggests_adding_a_whole_recipe(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    spinach = make_food(db, 2, "Spinach, raw", iron=6.0, energy=20)
    recipe = Recipe(id=1, user_id=1, name="Spinach bowl", servings=2)
    db.add(recipe)
    db.commit()

    by_food_id = {
        1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all(),
        2: db.query(FoodNutrient).filter(FoodNutrient.food_id == 2).all(),
    }
    # 1 serving = 100g spinach (200g total / 2 servings) -> +6mg iron = +60pp
    recipe_items = [WeightedFood(spinach, 100)]

    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[],
        limit=5,
        recipe_gap_candidates=[(recipe, recipe_items)],
    )

    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion.action == "add_recipe"
    assert suggestion.recipe_id == recipe.id
    assert suggestion.quantity_servings == pytest.approx(1.0)
    assert suggestion.food_id is None
    assert suggestion.quantity_g is None
    assert suggestion.food_name == "Spinach bowl"
    assert suggestion.before_percent_drv == pytest.approx(10.0)
    assert suggestion.after_percent_drv == pytest.approx(70.0)
    assert suggestion.calories_added == pytest.approx(20.0)  # 20kcal/100g * 100g
    assert "Spinach bowl" in suggestion.rationale


def test_add_recipe_cost_only_when_every_ingredient_priced(db):
    rice = make_food(db, 1, "Rice, white, cooked", iron=1.0)
    spinach = make_food(db, 2, "Spinach, raw", iron=6.0, energy=20)
    garlic = make_food(db, 3, "Garlic, raw", iron=2.0, energy=10)
    recipe = Recipe(id=1, user_id=1, name="Spinach & garlic", servings=1)
    db.add(recipe)
    db.commit()

    by_food_id = {
        1: db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).all(),
        2: db.query(FoodNutrient).filter(FoodNutrient.food_id == 2).all(),
        3: db.query(FoodNutrient).filter(FoodNutrient.food_id == 3).all(),
    }
    recipe_items = [WeightedFood(spinach, 100), WeightedFood(garlic, 10)]

    # only spinach priced — the whole recipe must have no fabricated cost
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[],
        limit=5,
        recipe_gap_candidates=[(recipe, recipe_items)],
        prices_by_food_id={2: 0.50},
    )
    assert len(suggestions) == 1
    assert suggestions[0].estimated_cost is None

    # both priced — now a real total is expected
    suggestions = suggest_meal_optimizations(
        db,
        other_items=[],
        swappable_items=[WeightedFood(rice, 100)],
        by_food_id=by_food_id,
        target_nutrient_key="iron",
        target_drv=10.0,
        gap_candidates=[],
        limit=5,
        recipe_gap_candidates=[(recipe, recipe_items)],
        prices_by_food_id={2: 0.50, 3: 1.00},
    )
    assert len(suggestions) == 1
    # 0.50 * 100/100 + 1.00 * 10/100 = 0.50 + 0.10
    assert suggestions[0].estimated_cost == pytest.approx(0.60)
