import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Food, FoodNutrient, Recipe, RecipeIngredient, User
from app.reference_patterns import AMINO_ACIDS
from app.search import (
    NutrientFilter,
    UnknownFilterKey,
    _rank_by_relevance,
    expand_query_terms,
    search_foods,
    search_foods_by_name,
    search_recipes,
)


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


def test_search_foods_eq_operator(db):
    make_food(db, 1, "exact match")
    make_food(db, 2, "different value")
    add_nutrient(db, 1, "fiber_total", 5.0)
    add_nutrient(db, 2, "fiber_total", 6.0)
    db.commit()

    results = search_foods(db, [NutrientFilter("fiber_total", "eq", 5.0)])
    assert [f.name for f in results] == ["exact match"]


def test_search_foods_pdcaas_score_filter(db):
    from app.reference_patterns import REFERENCE_PATTERNS
    pattern = REFERENCE_PATTERNS["child_3y_adult"]

    good = Food(
        id=1, name="good pdcaas", protein_g_per_100g=10,
        amino_acids=dict(pattern), digestibility_pdcaas=1.0,
    )
    bad = Food(
        id=2, name="no pdcaas data", protein_g_per_100g=10,
        amino_acids=dict(pattern), digestibility_pdcaas=None,
    )
    db.add_all([good, bad])
    db.commit()

    results = search_foods(db, [NutrientFilter("pdcaas_score", "gte", 90.0)])
    assert [f.name for f in results] == ["good pdcaas"]


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


def test_search_recipes_skips_recipes_with_no_ingredients(db):
    user = User(id=1, email="a@example.com", password_hash="x")
    db.add(user)
    empty_recipe = Recipe(id=1, user_id=1, name="empty", servings=1)
    db.add(empty_recipe)
    db.commit()

    results = search_recipes(db, user_id=1, filters=[])
    assert results == []


def test_search_recipes_diaas_score_filter(db):
    from app.reference_patterns import REFERENCE_PATTERNS
    pattern = REFERENCE_PATTERNS["child_3y_adult"]

    user = User(id=1, email="a@example.com", password_hash="x")
    db.add(user)
    food = Food(
        id=1, name="ingredient", protein_g_per_100g=10,
        amino_acids=dict(pattern), digestibility_diaas=dict.fromkeys(AMINO_ACIDS, 1.0),
    )
    db.add(food)
    recipe = Recipe(id=1, user_id=1, name="high quality recipe", servings=1)
    db.add(recipe)
    db.flush()
    db.add(RecipeIngredient(recipe_id=1, food_id=1, quantity_g=100))
    db.commit()

    results = search_recipes(db, user_id=1, filters=[NutrientFilter("diaas_score", "gte", 90.0)])
    assert [r.name for r in results] == ["high quality recipe"]

    results_none = search_recipes(db, user_id=1, filters=[NutrientFilter("diaas_score", "gte", 999.0)])
    assert results_none == []


def test_expand_query_terms_handles_plural():
    assert "egg" in expand_query_terms("eggs")
    assert "eggs" in expand_query_terms("egg")


def test_expand_query_terms_handles_synonyms():
    terms = expand_query_terms("egg")
    assert "hen egg" in terms
    terms2 = expand_query_terms("aubergine")
    assert "eggplant" in terms2


def test_expand_query_terms_avoids_double_s_mangling():
    # "grass" shouldn't singularize to "gras"
    terms = expand_query_terms("grass")
    assert "gras" not in terms


def test_search_foods_by_name_substring_match(db):
    make_food(db, 1, "Chicken, breast, cooked")
    make_food(db, 2, "Beef, ground, cooked")
    db.commit()

    results = search_foods_by_name(db, "chicken")
    assert [f.name for f in results] == ["Chicken, breast, cooked"]


def test_search_foods_by_name_plural_matches_singular_food(db):
    make_food(db, 1, "Egg, whole, cooked")
    db.commit()

    results = search_foods_by_name(db, "eggs")
    assert len(results) == 1
    assert results[0].name == "Egg, whole, cooked"


def test_search_foods_by_name_synonym_match(db):
    make_food(db, 1, "Aubergine, raw")
    db.commit()

    results = search_foods_by_name(db, "eggplant")
    assert len(results) == 1
    assert results[0].name == "Aubergine, raw"


def test_search_foods_by_name_ranks_exact_and_prefix_first():
    exact = Food(id=1, name="egg", protein_g_per_100g=1, amino_acids={})
    prefix = Food(id=2, name="egg substitute", protein_g_per_100g=1, amino_acids={})
    unrelated = Food(id=3, name="scrambled egg dish", protein_g_per_100g=1, amino_acids={})

    ranked = _rank_by_relevance([unrelated, prefix, exact], "egg", limit=10)
    assert ranked[0].name == "egg"
    assert ranked[1].name == "egg substitute"


def test_search_foods_by_name_surfaces_generic_food_over_branded_noise(db):
    """Regression test: branded products vastly outnumber generic
    Foundation/SR Legacy foods in production and are brand-name-prefixed,
    so a plain alphabetical candidate cutoff (ORDER BY name LIMIT N) can
    starve out a generic ingredient match before relevance ranking ever
    sees it. Enough branded "chickpea" noise here (all sorting ahead of
    "Chickpeas..." alphabetically) to reproduce that at limit=5,
    limit*5=25 candidate cutoff."""
    for i in range(30):
        db.add(
            Food(
                id=i + 1,
                name=f"{i:02d} Brand CHICKPEAS",
                protein_g_per_100g=5.0,
                amino_acids={},
                data_type="branded_food",
            )
        )
    db.add(
        Food(
            id=999,
            name="Chickpeas (garbanzo beans, bengal gram), mature seeds, raw",
            protein_g_per_100g=20.47,
            amino_acids={},
            data_type="sr_legacy_food",
        )
    )
    db.commit()

    results = search_foods_by_name(db, "chickpeas", limit=5)
    assert any(f.data_type == "sr_legacy_food" for f in results)


def test_search_foods_by_name_short_query_returns_empty(db):
    make_food(db, 1, "Chicken, breast, cooked")
    db.commit()
    assert search_foods_by_name(db, "c") == []


def test_search_foods_by_name_no_postgres_fuzzy_fallback_on_sqlite(db):
    """Confirms the pg_trgm-only fallback path is skipped gracefully (not
    an error) when the session isn't backed by Postgres — the whole point
    of gating it on db.bind.dialect.name."""
    make_food(db, 1, "Chicken, breast, cooked")
    db.commit()
    # a misspelling with no substring/synonym/plural match — on SQLite this
    # correctly returns nothing rather than raising, since the fuzzy
    # fallback that WOULD catch this is Postgres-only
    assert search_foods_by_name(db, "chiken") == []
