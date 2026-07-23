"""Tests for health_check.py — prompt section 5's read-only health-check
subsystem. Every test asserts the reported issue AND that nothing in the
database changed as a result (the whole point: "generate review reports
only, never silently modify public recipes")."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes import health_check
from app.stock_recipes.manifest import ManifestEntry
from app.stock_recipes.sources.base import RawRecipe, SourceUnavailable


class _FakeAdapter:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = 0

    def fetch(self, entry, cache_dir, force_refresh=False):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


MANIFEST_ENTRY = ManifestEntry(
    slug="health_test_recipe", name="Health Test Recipe", collections=["budget_meals"],
    source="fetch", source_name="schema_org", source_url="https://example.com/health-test-recipe",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    system_user = models.User(email="stock-recipes@nutrimatic.system", password_hash="x", is_system=True)
    session.add(system_user)
    session.flush()

    onion = models.Food(name="Onions, raw", protein_g_per_100g=1.1, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food")
    session.add(onion)
    session.flush()
    session.add(models.FoodNutrient(food_id=onion.id, nutrient_key="energy", amount_per_100g=40))

    recipe = models.Recipe(
        user_id=system_user.id, name="Health Test Recipe", servings=2, is_public=True,
        import_slug="health_test_recipe", source_name="schema_org", source_url=MANIFEST_ENTRY.source_url,
        source_licence="CC-BY-4.0", content_fingerprint="fp-original", match_coverage_lines=1.0,
        match_coverage_mass=1.0, unresolved_ingredients=[], stock_status="imported",
    )
    session.add(recipe)
    session.flush()

    ingredient = models.RecipeIngredient(recipe_id=recipe.id, food_id=onion.id, quantity_g=100)
    session.add(ingredient)
    session.flush()
    session.add(models.RecipeIngredientProvenance(
        recipe_ingredient_id=ingredient.id, raw_text="1 onion, chopped",
        match_method="alias", match_confidence=0.95,
    ))
    session.commit()

    monkeypatch.setattr(health_check, "load_manifest", lambda: [MANIFEST_ENTRY])

    return session, recipe, tmp_path / "cache"


def _snapshot(session, recipe_id):
    session.expire_all()
    recipe = session.query(models.Recipe).filter(models.Recipe.id == recipe_id).one()
    ingredients = session.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe_id).all()
    return recipe.stock_status, recipe.content_fingerprint, [(i.food_id, i.quantity_g) for i in ingredients]


def test_missing_licence_flagged(env, monkeypatch):
    session, recipe, cache_dir = env
    recipe.source_licence = None
    session.commit()

    monkeypatch.setattr(
        health_check, "build_adapters",
        lambda manual: {"schema_org": _FakeAdapter(error=SourceUnavailable("unreachable"))},
    )
    before = _snapshot(session, recipe.id)
    issues = health_check.run_health_check(session, cache_dir)
    after = _snapshot(session, recipe.id)

    assert before == after  # never modified
    assert any(i.issue_type == "missing_licence" for i in issues)


def test_dead_url_flagged_and_recipe_untouched(env, monkeypatch):
    session, recipe, cache_dir = env
    monkeypatch.setattr(
        health_check, "build_adapters",
        lambda manual: {"schema_org": _FakeAdapter(error=SourceUnavailable("404 not found"))},
    )
    before = _snapshot(session, recipe.id)
    issues = health_check.run_health_check(session, cache_dir)
    after = _snapshot(session, recipe.id)

    assert before == after
    assert before[0] == "imported"  # stock_status never flipped, unlike cmd_refresh
    dead = [i for i in issues if i.issue_type == "dead_url"]
    assert len(dead) == 1
    assert "404" in dead[0].detail


def test_redirect_flagged(env, monkeypatch):
    session, recipe, cache_dir = env
    raw = RawRecipe(
        name="Health Test Recipe", servings=2, ingredient_lines=["1 onion, chopped"],
        canonical_url=MANIFEST_ENTRY.source_url, source_licence="CC-BY-4.0",
        content_fingerprint="fp-original", resolved_url="https://example.com/new-location",
    )
    monkeypatch.setattr(health_check, "build_adapters", lambda manual: {"schema_org": _FakeAdapter(result=raw)})

    issues = health_check.run_health_check(session, cache_dir)
    redirects = [i for i in issues if i.issue_type == "redirect"]
    assert len(redirects) == 1
    assert "new-location" in redirects[0].detail


def test_no_issues_when_nothing_changed(env, monkeypatch):
    session, recipe, cache_dir = env
    raw = RawRecipe(
        name="Health Test Recipe", servings=2, ingredient_lines=["1 onion, chopped"],
        canonical_url=MANIFEST_ENTRY.source_url, source_licence="CC-BY-4.0",
        content_fingerprint="fp-original", resolved_url=MANIFEST_ENTRY.source_url,
    )
    monkeypatch.setattr(health_check, "build_adapters", lambda manual: {"schema_org": _FakeAdapter(result=raw)})

    issues = health_check.run_health_check(session, cache_dir)
    assert issues == []


def test_content_and_ingredients_changed_recommend_rematch(env, monkeypatch):
    session, recipe, cache_dir = env
    raw = RawRecipe(
        name="Health Test Recipe", servings=2,
        ingredient_lines=["1 onion, chopped", "2 cloves garlic, crushed"],
        canonical_url=MANIFEST_ENTRY.source_url, source_licence="CC-BY-4.0",
        content_fingerprint="fp-changed", resolved_url=MANIFEST_ENTRY.source_url,
    )
    monkeypatch.setattr(health_check, "build_adapters", lambda manual: {"schema_org": _FakeAdapter(result=raw)})

    before = _snapshot(session, recipe.id)
    issues = health_check.run_health_check(session, cache_dir)
    after = _snapshot(session, recipe.id)

    assert before == after
    by_type = {i.issue_type for i in issues}
    assert "content_changed" in by_type
    assert "ingredients_changed" in by_type
    assert "rematch_recommended" in by_type


def test_write_health_report_json_and_csv(env, tmp_path):
    issues = [health_check.HealthIssue(1, "slug-a", "Recipe A", "dead_url", "404 not found")]
    report_path = tmp_path / "report.json"

    health_check.write_health_report(report_path, issues)

    assert report_path.exists()
    assert report_path.with_suffix(".csv").exists()
    import json
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data == [{"recipe_id": 1, "slug": "slug-a", "name": "Recipe A", "issue_type": "dead_url", "detail": "404 not found"}]
