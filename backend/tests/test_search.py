import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
from app.reference_patterns import AMINO_ACIDS
from app.search import NutrientFilter, UnknownFilterKey, search_foods, search_recipes


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_food(db, id_, name, protein=10.0, aa_value=20.0, diaas=None, pdcaas=None):
    food = Food(
        id=id_, name=name, protein_g_per_100g=protein,
        amino_acids=dict.fromkeys(AMINO_ACIDS, aa_value),
        digestibility_diaas=dict.fromkeys(AMINO_ACIDS, diaas) if diaas is not None else None,
        digestibility_pdcaas=pdcaas,
    )
    db.add(food)
    db.flush()
    return food


def add_nutrient(db, food_id, key, amount):
    db.add(FoodNutrient(food_id=food_id, nutrient_key=key, amount_per_100g=amount))


def test_search_foods_single_nutrient_filter(db):
    make_food(db, 1, "high fibre food")
    make_food(db, 2, "low fibre food")
    add_nutrient(db, 1, "fiber_total", 10.0)
    add_nutrient(db, 2, "fiber_total", 1.0)
    db.commit()

    results = search_foods(db, [NutrientFilter("fiber_total", "gte", 5.0)])
    assert [f.name for f in results] == ["high fibre food"]


def test_search_foods_multiple_filters_are_anded(db):
    make_food(db, 1, "matches both")
    make_food(db, 2, "only high fibre")
    add_nutrient(db, 1, "fiber_total", 10.0)
    add_nutrient(db, 1, "energy", 100.0)
    add_nutrient(db, 2, "fiber_total", 10.0)
    add_nutrient(db, 2, "energy", 500.0)
    db.commit()

    results = search_foods(
        db, [NutrientFilter("fiber_total", "gte", 5.0), NutrientFilter("energy", "lte", 200.0)]
    )
    assert [f.name for f in results] == ["matches both"]


def test_search_foods_protein_filter(db):
    make_food(db, 1, "high protein", protein=30.0)
    make_food(db, 2, "low protein", protein=2.0)
    db.commit()

    results = search_foods(db, [NutrientFilter("protein_g_per_100g", "gte", 20.0)])
    assert [f.name for f in results] == ["high protein"]


def test_search_foods_diaas_score_filter(db):
    # matches PATTERN exactly with digestibility=1.0 -> DIAAS = 100
    from app.reference_patterns import REFERENCE_PATTERNS
    pattern = REFERENCE_PATTERNS["child_3y_adult"]

    good = Food(
        id=1, name="good diaas", protein_g_per_100g=10,
        amino_acids=dict(pattern), digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 1.0),
    )
    bad = Food(
        id=2, name="no digestibility data", protein_g_per_100g=10,
        amino_acids=dict(pattern), digestibility_diaas=None,
    )
    db.add_all([good, bad])
    db.commit()

    results = search_foods(db, [NutrientFilter("diaas_score", "gte", 90.0)])
    assert [f.name for f in results] == ["good diaas"]


def test_search_foods_unknown_key_raises(db):
    with pytest.raises(UnknownFilterKey):
        search_foods(db, [NutrientFilter("not_a_real_key", "gte", 1.0)])


def test_search_recipes_scoped_to_user_and_filters(db):
    user = User(id=1, email="a@example.com", password_hash="x")
    other_user = User(id=2, email="b@example.com", password_hash="x")
    db.add_all([user, other_user])

    food = make_food(db, 1, "ingredient", protein=10.0)
    add_nutrient(db, 1, "fiber_total", 8.0)

    mine = Recipe(id=1, user_id=1, name="my recipe", servings=2)
    others = Recipe(id=2, user_id=2, name="not mine", servings=2)
    db.add_all([mine, others])
    db.flush()
    db.add(RecipeIngredient(recipe_id=1, food_id=1, quantity_g=200))
    db.add(RecipeIngredient(recipe_id=2, food_id=1, quantity_g=200))
    db.commit()

    # per serving: 8.0 * 200/100 / 2 servings = 8.0
    results = search_recipes(db, user_id=1, filters=[NutrientFilter("fiber_total", "gte", 5.0)])
    assert [r.name for r in results] == ["my recipe"]


def test_search_recipes_unknown_key_raises(db):
    user = User(id=1, email="a@example.com", password_hash="x")
    db.add(user)
    db.commit()
    with pytest.raises(UnknownFilterKey):
        search_recipes(db, user_id=1, filters=[NutrientFilter("protein_g_per_100g", "gte", 1.0)])
