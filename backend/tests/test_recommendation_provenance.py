"""Tests for recommendation_provenance.py — hardening prompt 4: exact,
regional, analogue, proxy, reviewed-substitution, fallback-resolved,
mixed-quality, and legacy-null (no provenance at all) cases."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food, Recipe, RecipeIngredient, RecipeIngredientProvenance, User
from app.reference_patterns import AMINO_ACIDS
from app.recommendation_provenance import compute_recipe_quality_summary


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db):
    user = User(email="a@example.com", password_hash="x", is_system=True)
    db.add(user)
    db.commit()
    return user


def make_food(db, name="Food"):
    food = Food(name=name, protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    db.add(food)
    db.commit()
    return food


def make_recipe(db, user, **kwargs):
    recipe = Recipe(user_id=user.id, name="Test Recipe", servings=1, **kwargs)
    db.add(recipe)
    db.commit()
    return recipe


def add_ingredient(db, recipe, food, quantity_g=100.0):
    ingredient = RecipeIngredient(recipe_id=recipe.id, food_id=food.id, quantity_g=quantity_g)
    db.add(ingredient)
    db.commit()
    return ingredient


def add_provenance(db, ingredient, **kwargs):
    defaults = dict(raw_text="1 unit food")
    defaults.update(kwargs)
    provenance = RecipeIngredientProvenance(recipe_ingredient_id=ingredient.id, **defaults)
    db.add(provenance)
    db.commit()
    return provenance


def test_exact_relationship_counted(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="exact", match_confidence=1.0)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.exact_or_regional_count == 1
    assert summary.proportion_exact_or_regional == 1.0
    assert summary.unmapped_count == 0


def test_regional_equivalent_counted_with_exact(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="regional_equivalent", match_confidence=0.9)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.exact_or_regional_count == 1
    assert summary.analogue_count == 0


def test_canonical_and_exact_name_methods_count_as_exact_with_no_relationship(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ing_a = add_ingredient(db, recipe, make_food(db, "A"))
    ing_b = add_ingredient(db, recipe, make_food(db, "B"))
    add_provenance(db, ing_a, match_method="canonical", match_relationship=None, match_confidence=1.0)
    add_provenance(db, ing_b, match_method="exact_name", match_relationship=None, match_confidence=1.0)

    summary = compute_recipe_quality_summary(db, recipe, [ing_a, ing_b])
    assert summary.exact_or_regional_count == 2


def test_analogue_relationship_counted(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="close_analogue", match_confidence=0.7)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.analogue_count == 1
    assert summary.proportion_analogue == 1.0


def test_category_proxy_counted_separately_from_exact(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="category_proxy", match_confidence=0.4)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.proxy_or_reviewed_count == 1
    assert summary.exact_or_regional_count == 0


def test_reviewed_substitution_never_treated_as_exact(db):
    """A manually reviewed substitution is a human-approved pairing, not
    a semantically exact one — prompt 4's explicit instruction."""
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(
        db, ingredient, match_method="manual_review", match_relationship="reviewed_substitution", match_confidence=0.95,
    )

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.proxy_or_reviewed_count == 1
    assert summary.exact_or_regional_count == 0


def test_fallback_resolution_counted(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(
        db, ingredient, match_method="alias", match_relationship="exact",
        match_confidence=0.8, match_used_fallback=True,
    )

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.fallback_resolution_count == 1


def test_mixed_quality_recipe_proportions(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ing_exact = add_ingredient(db, recipe, make_food(db, "Exact"), quantity_g=100.0)
    ing_analogue = add_ingredient(db, recipe, make_food(db, "Analogue"), quantity_g=100.0)
    ing_proxy = add_ingredient(db, recipe, make_food(db, "Proxy"), quantity_g=100.0)
    add_provenance(db, ing_exact, match_method="alias", match_relationship="exact", match_confidence=1.0)
    add_provenance(db, ing_analogue, match_method="alias", match_relationship="close_analogue", match_confidence=0.6)
    add_provenance(db, ing_proxy, match_method="alias", match_relationship="category_proxy", match_confidence=0.3)

    summary = compute_recipe_quality_summary(db, recipe, [ing_exact, ing_analogue, ing_proxy])
    assert summary.exact_or_regional_count == 1
    assert summary.analogue_count == 1
    assert summary.proxy_or_reviewed_count == 1
    assert summary.proportion_exact_or_regional == pytest.approx(1 / 3)
    assert summary.min_mapping_confidence == pytest.approx(0.3)
    # unweighted average would be 0.6333; equal masses here so weighted == flat average
    assert summary.weighted_mapping_confidence == pytest.approx((1.0 + 0.6 + 0.3) / 3)
    assert summary.unresolved_or_low_confidence_count == 1  # only the 0.3 proxy is below 0.5


def test_weighted_confidence_reflects_ingredient_mass(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    heavy = add_ingredient(db, recipe, make_food(db, "Heavy"), quantity_g=900.0)
    light = add_ingredient(db, recipe, make_food(db, "Light"), quantity_g=100.0)
    add_provenance(db, heavy, match_method="alias", match_relationship="exact", match_confidence=1.0)
    add_provenance(db, light, match_method="alias", match_relationship="category_proxy", match_confidence=0.2)

    summary = compute_recipe_quality_summary(db, recipe, [heavy, light])
    # dominated by the 900g exact-match ingredient, unlike a flat average (0.6)
    assert summary.weighted_mapping_confidence == pytest.approx(0.92)


def test_legacy_null_recipe_has_no_provenance_rows_at_all(db):
    """A stock recipe imported before per-ingredient provenance tracking
    existed (or a plain user-built recipe) — no RecipeIngredientProvenance
    rows at all. Must degrade gracefully, never crash, never fabricate a
    confidence number."""
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="legacy_test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    # deliberately no add_provenance() call

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.unmapped_count == 1
    assert summary.exact_or_regional_count == 0
    assert summary.min_mapping_confidence is None
    assert summary.weighted_mapping_confidence is None
    assert summary.proportion_exact_or_regional is None


def test_plain_user_recipe_has_no_provenance_and_no_coverage(db):
    user = make_user(db)
    recipe = make_recipe(db, user)  # no import_slug — an ordinary user-built recipe
    ingredient = add_ingredient(db, recipe, make_food(db))

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.unmapped_count == 1
    assert summary.nutrient_coverage is None  # match_coverage_mass was never set


def test_unresolved_ingredient_lines_counted(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test", unresolved_ingredients=["2 tbsp mystery sauce"])
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="exact", match_confidence=1.0)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.unresolved_or_low_confidence_count == 1


def test_fuzzy_match_with_no_relationship_counted_separately(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test")
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="fuzzy", match_relationship=None, match_confidence=0.6)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.fuzzy_unclassified_count == 1
    assert summary.exact_or_regional_count == 0
    assert summary.analogue_count == 0
    assert summary.proxy_or_reviewed_count == 0


def test_nutrient_coverage_reuses_match_coverage_mass_verbatim(db):
    user = make_user(db)
    recipe = make_recipe(db, user, import_slug="test", match_coverage_mass=0.73)
    ingredient = add_ingredient(db, recipe, make_food(db))
    add_provenance(db, ingredient, match_method="alias", match_relationship="exact", match_confidence=1.0)

    summary = compute_recipe_quality_summary(db, recipe, [ingredient])
    assert summary.nutrient_coverage == pytest.approx(0.73)
