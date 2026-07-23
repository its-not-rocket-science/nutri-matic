"""Pipeline/import tests — prompt section 16: idempotent reruns, duplicate
detection, source updates, review approval, public visibility, stock
ownership, rollback on failure. Runs the real discover/fetch/parse/match/
analyse/review-export/import-approved/refresh stages against an isolated
SQLite database and a small in-test manifest — never the real 250-entry
seed_data/manifest.json or a live network request."""

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes import pipeline
from app.stock_recipes.manifest import ManifestEntry
from app.stock_recipes.sources.base import RawRecipe, SourceUnavailable


def _args(cache_dir: Path, **overrides) -> SimpleNamespace:
    defaults = dict(
        cache_dir=cache_dir, source=None, collection=None, limit=None, verbose=False,
        force_refresh=False, dry_run=False, minimum_match_coverage=pipeline.DEFAULT_MINIMUM_MATCH_COVERAGE,
        simulation_count=30, random_seed=42, review_file=cache_dir / "review.json",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


MANIFEST = [
    ManifestEntry(
        slug="bean_chilli_test", name="Bean Chilli", collections=["budget_meals"],
        source="manual", source_name="manual", source_url=None,
    ),
    ManifestEntry(
        slug="tomato_soup_test", name="Tomato Soup", collections=["budget_meals"],
        source="manual", source_name="manual", source_url=None,
    ),
    ManifestEntry(
        slug="tomato_soup_with_bread_test", name="Tomato Soup with Bread", collections=["budget_meals"],
        source="manual", source_name="manual", source_url=None,
    ),
]
MANUAL_RECIPES = {
    "bean_chilli_test": {
        "servings": 4,
        "ingredients": ["400 g tin kidney beans, drained", "1 onion, chopped", "400 g tin chopped tomatoes"],
    },
    "tomato_soup_test": {
        "servings": 2,
        "ingredients": ["400 g tin chopped tomatoes", "1 onion, chopped"],
    },
    "tomato_soup_with_bread_test": {
        "servings": 2,
        "ingredients": ["400 g tin chopped tomatoes", "1 onion, chopped", "2 slices bread"],
    },
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)
    session = TestSessionLocal()

    def food(name, protein=5.0):
        f = models.Food(name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="foundation_food")
        session.add(f)
        session.flush()
        session.add(models.FoodNutrient(food_id=f.id, nutrient_key="sodium", amount_per_100g=50))
        return f

    food("Kidney beans, canned")
    food("Onions, raw")
    food("Tomatoes, canned, red, ripe")
    food("Bread, whole wheat")
    session.commit()
    session.close()

    monkeypatch.setattr(pipeline, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(pipeline, "load_manifest", lambda: list(MANIFEST))
    monkeypatch.setattr(pipeline, "load_manual_recipes", lambda: dict(MANUAL_RECIPES))

    return SimpleNamespace(engine=engine, SessionLocal=TestSessionLocal, cache_dir=tmp_path / "cache")


def _run_pipeline_to_review(env, args) -> None:
    pipeline.cmd_discover(args)
    pipeline.cmd_fetch(args)
    pipeline.cmd_parse(args)
    pipeline.cmd_match(args)
    pipeline.cmd_analyse(args)
    pipeline.cmd_review_export(args)


def _approve_all(review_file: Path) -> None:
    rows = json.loads(review_file.read_text(encoding="utf-8"))
    for row in rows:
        row["proposed_publication_status"] = "approved"
    review_file.write_text(json.dumps(rows), encoding="utf-8")
    csv_path = review_file.with_suffix(".csv")
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows_csv = list(csv.DictReader(f))
    for row in rows_csv:
        row["proposed_publication_status"] = "approved"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=pipeline._CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows_csv)


def test_full_pipeline_imports_recipes(env):
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)

    rc = pipeline.cmd_import_approved(args)
    assert rc == 0

    session = env.SessionLocal()
    recipes = session.query(models.Recipe).all()
    assert len(recipes) == 3
    assert {r.name for r in recipes} == {"Bean Chilli", "Tomato Soup", "Tomato Soup with Bread"}
    for r in recipes:
        assert r.is_public is True
        assert r.stock_status == "imported"
        assert r.import_slug is not None
    session.close()


def test_stock_ownership_via_explicit_system_flag(env):
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    session = env.SessionLocal()
    system_users = session.query(models.User).filter(models.User.is_system.is_(True)).all()
    assert len(system_users) == 1
    recipes = session.query(models.Recipe).all()
    assert all(r.user_id == system_users[0].id for r in recipes)
    session.close()


def test_idempotent_rerun_does_not_duplicate(env):
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    # rerun the entire pipeline from scratch against the same cache — same
    # candidates, same review decisions
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    session = env.SessionLocal()
    assert session.query(models.Recipe).count() == 3
    assert session.query(models.User).filter(models.User.is_system.is_(True)).count() == 1
    assert session.query(models.Collection).count() == len(pipeline.COLLECTIONS)
    session.close()


def _set_csv_status(review_file: Path, statuses: dict[str, str]) -> None:
    """Edits the review CSV's proposed_publication_status column — the
    actual maintainer-editable surface import-approved reads (see
    pipeline._load_review: the CSV overlays the JSON, not the other way
    round), so tests that approve/reject specific rows must edit it rather
    than the JSON directly."""
    csv_path = review_file.with_suffix(".csv")
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows_csv = list(csv.DictReader(f))
    for row in rows_csv:
        if row["slug"] in statuses:
            row["proposed_publication_status"] = statuses[row["slug"]]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=pipeline._CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows_csv)


def test_duplicate_candidates_flagged_not_merged(env, monkeypatch):
    # a pair whose normalised-title similarity is deliberately above
    # dedup.TITLE_SIMILARITY_THRESHOLD, distinct from the other tests'
    # fixture recipes so their exact-count/name assertions are unaffected
    near_dupe_manifest = [
        ManifestEntry(slug="chicken_curry_rice_test", name="Chicken Curry Rice", collections=["everyday_uk_meals"], source="manual", source_name="manual", source_url=None),
        ManifestEntry(slug="chicken_curry_with_rice_test", name="Chicken Curry with Rice", collections=["everyday_uk_meals"], source="manual", source_name="manual", source_url=None),
    ]
    near_dupe_recipes = {
        "chicken_curry_rice_test": {"servings": 2, "ingredients": ["1 onion, chopped", "400 g tin chopped tomatoes"]},
        "chicken_curry_with_rice_test": {"servings": 2, "ingredients": ["1 onion, chopped", "400 g tin chopped tomatoes", "2 slices bread"]},
    }
    monkeypatch.setattr(pipeline, "load_manifest", lambda: near_dupe_manifest)
    monkeypatch.setattr(pipeline, "load_manual_recipes", lambda: near_dupe_recipes)

    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)

    cache = pipeline._load_cache(env.cache_dir)
    assert cache["chicken_curry_rice_test"]["duplicate_candidates"], "similar titles should be flagged"
    assert cache["chicken_curry_with_rice_test"]["duplicate_candidates"]

    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)
    session = env.SessionLocal()
    # flagged, never auto-merged — both still become separate recipes
    names = {r.name for r in session.query(models.Recipe).all()}
    assert "Chicken Curry Rice" in names and "Chicken Curry with Rice" in names
    session.close()


def test_review_rejected_candidate_is_not_imported(env):
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)

    _set_csv_status(args.review_file, {
        "bean_chilli_test": "rejected",
        "tomato_soup_test": "approved",
        "tomato_soup_with_bread_test": "approved",
    })

    pipeline.cmd_import_approved(args)
    session = env.SessionLocal()
    names = {r.name for r in session.query(models.Recipe).all()}
    assert "Bean Chilli" not in names
    assert "Tomato Soup" in names
    session.close()


def test_import_refuses_unedited_review_file(env):
    """Default proposed_publication_status is "needs_review" — an
    unedited review file must publish nothing (prompt section 13's
    "no command should publish unreviewed recipes accidentally")."""
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)

    pipeline.cmd_import_approved(args)  # review file left untouched
    session = env.SessionLocal()
    assert session.query(models.Recipe).count() == 0
    session.close()


def test_rollback_on_failure_imports_nothing(env):
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)

    rows = json.loads(args.review_file.read_text(encoding="utf-8"))
    # corrupt one approved row so _import_one hits a NOT NULL violation
    # partway through the batch
    for row in rows:
        if row["slug"] == "tomato_soup_test":
            for m in row["matches"]:
                if m["resolved"]:
                    m["food_id"] = None
    args.review_file.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(Exception):
        pipeline.cmd_import_approved(args)

    session = env.SessionLocal()
    # the whole batch (incl. the other two valid rows) must be rolled back —
    # not a partial import
    assert session.query(models.Recipe).count() == 0
    session.close()


def test_refresh_flags_needs_review_without_touching_ingredients(env, monkeypatch):
    fetch_entry = ManifestEntry(
        slug="fetch_soup_test", name="Fetch Soup", collections=["budget_meals"],
        source="fetch", source_name="schema_org", source_url="https://example.com/recipes/soup/",
    )
    monkeypatch.setattr(pipeline, "load_manifest", lambda: [fetch_entry])
    monkeypatch.setattr(pipeline, "load_manual_recipes", lambda: {})

    class _FakeAdapter:
        def __init__(self, ingredient_lines, fingerprint):
            self.ingredient_lines = ingredient_lines
            self.fingerprint = fingerprint

        def fetch(self, entry, cache_dir, force_refresh=False):
            return RawRecipe(
                name=entry.name, servings=2, ingredient_lines=self.ingredient_lines,
                canonical_url=entry.source_url, source_licence=None, content_fingerprint=self.fingerprint,
            )

    original_adapter = _FakeAdapter(["400 g tin chopped tomatoes", "1 onion, chopped"], "fp-v1")
    monkeypatch.setattr(pipeline, "build_adapters", lambda manual: {"schema_org": original_adapter})

    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    session = env.SessionLocal()
    recipe = session.query(models.Recipe).filter(models.Recipe.import_slug == "fetch_soup_test").one()
    ingredient_count_before = session.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe.id).count()
    assert ingredient_count_before > 0
    assert recipe.content_fingerprint == "fp-v1"
    session.close()

    # source content changes — refresh must flag it, not silently rewrite it
    changed_adapter = _FakeAdapter(["800 g tin chopped tomatoes", "2 onions, chopped"], "fp-v2")
    monkeypatch.setattr(pipeline, "build_adapters", lambda manual: {"schema_org": changed_adapter})
    pipeline.cmd_refresh(args)

    session = env.SessionLocal()
    recipe = session.query(models.Recipe).filter(models.Recipe.import_slug == "fetch_soup_test").one()
    assert recipe.stock_status == "needs_review"
    ingredient_count_after = session.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe.id).count()
    assert ingredient_count_after == ingredient_count_before  # untouched
    session.close()


def test_refresh_unavailable_source_flags_status(env, monkeypatch):
    fetch_entry = ManifestEntry(
        slug="fetch_gone_test", name="Fetch Gone", collections=["budget_meals"],
        source="fetch", source_name="schema_org", source_url="https://example.com/recipes/gone/",
    )
    monkeypatch.setattr(pipeline, "load_manifest", lambda: [fetch_entry])
    monkeypatch.setattr(pipeline, "load_manual_recipes", lambda: {})

    class _AvailableThenGoneAdapter:
        def __init__(self):
            self.calls = 0

        def fetch(self, entry, cache_dir, force_refresh=False):
            self.calls += 1
            if self.calls == 1:
                return RawRecipe(
                    name=entry.name, servings=2, ingredient_lines=["1 onion, chopped"],
                    canonical_url=entry.source_url, source_licence=None, content_fingerprint="fp-1",
                )
            raise SourceUnavailable("404")

    adapter = _AvailableThenGoneAdapter()
    monkeypatch.setattr(pipeline, "build_adapters", lambda manual: {"schema_org": adapter})

    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    pipeline.cmd_refresh(args)
    session = env.SessionLocal()
    recipe = session.query(models.Recipe).filter(models.Recipe.import_slug == "fetch_gone_test").one()
    assert recipe.stock_status == "source_unavailable"
    session.close()


def test_import_persists_match_relationship(env):
    """prompt section 8: the alias/proxy relationship food_matching.py
    resolved a match with must survive all the way into
    RecipeIngredientProvenance, not just match_method/match_confidence."""
    args = _args(env.cache_dir)
    _run_pipeline_to_review(env, args)
    _approve_all(args.review_file)
    pipeline.cmd_import_approved(args)

    session = env.SessionLocal()
    recipe = session.query(models.Recipe).filter(models.Recipe.name == "Bean Chilli").one()
    provenance_rows = (
        session.query(models.RecipeIngredientProvenance)
        .join(models.RecipeIngredient, models.RecipeIngredient.id == models.RecipeIngredientProvenance.recipe_ingredient_id)
        .filter(models.RecipeIngredient.recipe_id == recipe.id)
        .all()
    )
    assert provenance_rows
    alias_rows = [p for p in provenance_rows if p.match_method == "alias"]
    assert alias_rows
    assert all(p.match_relationship is not None for p in alias_rows)
    session.close()


def test_upsert_robustness_retains_history_and_flags_latest(env):
    """prompt section 4: a new analysis run must never overwrite a past
    RobustnessResult row — it inserts a new one and demotes whatever
    row previously had is_latest=True, so full history survives for
    auditing/debugging/scientific comparison."""
    session = env.SessionLocal()
    system_user = models.User(email="stock-recipes@nutrimatic.system", password_hash="x", is_system=True)
    session.add(system_user)
    session.flush()
    recipe = models.Recipe(
        user_id=system_user.id, name="History Test Recipe", servings=1, is_public=True,
        import_slug="history_test",
    )
    session.add(recipe)
    session.flush()

    first = {
        "model_version": "1.0.0", "simulation_count": 10, "random_seed": 1,
        "metrics": {}, "overall_rating": 3, "overall_explanation": "first run",
    }
    pipeline._upsert_robustness(session, recipe, first)
    session.commit()

    second = {
        "model_version": "1.0.1", "simulation_count": 20, "random_seed": 2,
        "metrics": {}, "overall_rating": 4, "overall_explanation": "second run, model updated",
    }
    pipeline._upsert_robustness(session, recipe, second)
    session.commit()

    rows = (
        session.query(models.RobustnessResult)
        .filter(models.RobustnessResult.recipe_id == recipe.id)
        .order_by(models.RobustnessResult.id)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].is_latest is False
    assert rows[0].model_version == "1.0.0"
    assert rows[0].overall_explanation == "first run"
    assert rows[1].is_latest is True
    assert rows[1].model_version == "1.0.1"
    assert rows[1].overall_explanation == "second run, model updated"
    session.close()


def test_cmd_validate_aliases_clean_registry_returns_zero(env):
    """prompt section 4's standalone registry-validation command — clean
    against the real alias tables and an empty database (nothing pinned
    means nothing to check at the database level either)."""
    args = _args(env.cache_dir)
    assert pipeline.cmd_validate_aliases(args) == 0


def test_cmd_validate_aliases_reports_dangling_preferred_target(env, monkeypatch):
    from app.stock_recipes.ingredient_aliases import REVIEWED_FALLBACKS, reviewed

    monkeypatch.setitem(
        REVIEWED_FALLBACKS, "qorvantrix cli test ingredient",
        reviewed("onions raw", "test-only dangling id", food_id=999_999, expected_food_name="Onions, raw"),
    )
    args = _args(env.cache_dir)
    assert pipeline.cmd_validate_aliases(args) == 1
