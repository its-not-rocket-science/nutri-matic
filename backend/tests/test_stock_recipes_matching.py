"""Matching tests — prompt section 16: exact aliases, fuzzy candidates,
unresolved ingredients, low-confidence matches, branded ingredients,
mass-weighted coverage."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import (
    compute_coverage,
    match_ingredient,
    normalise_ingredient_name,
    validate_reviewed_mappings,
)
from app.stock_recipes.ingredient_aliases import REVIEWED_FALLBACKS, reviewed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()

    foods = [
        Food(name="Onions, raw", protein_g_per_100g=1.1, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food"),
        Food(name="Garlic, raw", protein_g_per_100g=6.4, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food"),
        Food(name="Tomatoes, canned, red, ripe, packed in tomato juice", protein_g_per_100g=0.8, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food"),
        Food(name="Beef, ground, 85% lean meat / 15% fat, raw", protein_g_per_100g=17.2, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="foundation_food"),
        Food(name="Broccoli, raw", protein_g_per_100g=2.8, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="foundation_food"),
        Food(name="XYZ Brand Mystery Snack Bar", protein_g_per_100g=5.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="branded_food"),
    ]
    session.add_all(foods)
    session.commit()
    yield session
    session.close()


def test_exact_alias_match(db):
    result = match_ingredient(db, "onions")
    assert result.method == "alias"
    assert result.food.name == "Onions, raw"
    assert result.confidence == 0.95


def test_prefers_duplicate_with_complete_amino_acid_profile(db):
    """The real-world case this guards: the same food commonly exists
    twice in FDC (a Foundation Foods entry and an SR Legacy entry — e.g.
    "Garlic, raw"), and only one of the two actually has amino acid data.
    Found blocking DIAAS/PDCAAS on ~180 imported recipes because ranking
    only considered name length/alphabetical order, not data
    completeness."""
    complete = {a: 40.0 for a in AMINO_ACIDS}
    incomplete = dict.fromkeys(AMINO_ACIDS)

    # incomplete entry added first / lower id, so a naive tiebreak would pick it
    db.add(Food(name="Celery, raw", protein_g_per_100g=0.5, amino_acids=incomplete, data_type="foundation_food"))
    db.add(Food(name="Celery, raw", protein_g_per_100g=0.5, amino_acids=complete, data_type="sr_legacy_food"))
    db.commit()

    result = match_ingredient(db, "celery")
    assert result.method == "canonical"
    assert all(v is not None for v in result.food.amino_acids.values())


def test_alias_matches_within_a_longer_ingredient_phrase(db):
    result = match_ingredient(db, "5% lean beef mince")
    assert result.method == "alias"
    assert result.food.name.startswith("Beef, ground")


def test_canonical_deterministic_match(db):
    # "broccoli" has no ALIASES entry — resolved via the deterministic
    # Food.name prefix lookup instead
    result = match_ingredient(db, "broccoli")
    assert result.method == "canonical"
    assert result.food.name == "Broccoli, raw"


def test_unresolved_ingredient_returns_no_food(db):
    result = match_ingredient(db, "unobtainium powder")
    assert result.unresolved is True
    assert result.food is None
    assert result.method is None


def test_branded_food_gets_low_fuzzy_confidence(db):
    # "mystery snack bar" matches nothing via alias/canonical, only the
    # fuzzy tier — and the only real substring hit is the branded product
    result = match_ingredient(db, "mystery snack bar")
    assert result.method == "fuzzy"
    assert result.confidence == 0.4  # branded == "low" data_type confidence


def test_candidates_list_populated_even_when_unresolved(db):
    # a near-miss should still surface as a candidate for the review file,
    # even if it's not confident enough to auto-accept
    result = match_ingredient(db, "onion rings")
    # "onion" is a substring, so the fuzzy candidate list should include it
    assert any(c.name == "Onions, raw" for c in result.candidates)


def test_normalise_strips_container_words():
    assert normalise_ingredient_name("Tin Chopped Tomatoes") == "chopped tomatoes"
    assert normalise_ingredient_name("  Packet of stuffing mix  ") == "stuffing mix"


def test_normalise_ingredient_name_is_the_same_function_reexported_from_linguistic_normalisation():
    """prompt section 10: linguistic normalisation lives in its own
    module now — food_matching.normalise_ingredient_name must be that
    same function re-exported, not an independent copy that could drift."""
    from app.stock_recipes.linguistic_normalisation import normalise_ingredient_name as direct

    assert normalise_ingredient_name is direct


def test_coverage_line_and_mass():
    coverage = compute_coverage([(True, 100.0), (True, 50.0), (False, None)])
    assert coverage.line_coverage == pytest.approx(2 / 3)
    assert coverage.mass_coverage == 1.0  # only lines with known mass count toward the denominator


def test_coverage_mass_weighted_penalises_large_unresolved_ingredient():
    # a small unresolved line barely dents mass coverage...
    small_gap = compute_coverage([(True, 490.0), (False, 10.0)])
    # ...but a large one does, even with the same line coverage
    big_gap = compute_coverage([(True, 10.0), (False, 490.0)])
    assert small_gap.line_coverage == big_gap.line_coverage == 0.5
    assert small_gap.mass_coverage > big_gap.mass_coverage


def test_coverage_defaults_to_full_mass_when_nothing_has_a_known_mass():
    coverage = compute_coverage([(True, None), (False, None)])
    assert coverage.mass_coverage == 1.0


def test_coverage_empty_list():
    coverage = compute_coverage([])
    assert coverage.line_coverage == 0.0
    assert coverage.mass_coverage == 0.0


# --- prompt section 2: stable food_id targets for reviewed mappings --------

def test_reviewed_mapping_resolves_via_food_id_ignoring_bad_search_phrase(db, monkeypatch):
    """A food_id-pinned mapping must resolve straight to that row, even
    when its fallback search_phrase would match nothing (or something
    else) — the id is the primary target, description search is only a
    fallback (prompt section 2)."""
    pinned = Food(
        name="Zzyzx Pinned Reference Food, raw", protein_g_per_100g=1.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add(pinned)
    db.commit()

    target = reviewed(
        "this search phrase matches absolutely nothing in the fixture",
        "test-only reviewed mapping, pinned by id",
        food_id=pinned.id, expected_food_name=pinned.name,
    )
    monkeypatch.setitem(REVIEWED_FALLBACKS, "qorvantrix placeholder ingredient", target)

    result = match_ingredient(db, "qorvantrix placeholder ingredient")
    assert result.method == "manual_review"
    assert result.food.id == pinned.id
    assert result.relationship == "reviewed_substitution"


def test_reviewed_mapping_falls_back_to_search_phrase_when_food_id_missing(db, monkeypatch):
    """If the pinned id no longer exists (food deleted/re-ingested under a
    new id), resolution must fall back to the description search rather
    than failing outright."""
    target = reviewed(
        "onions raw",
        "test-only reviewed mapping with a dangling id",
        food_id=999_999, expected_food_name="Onions, raw",
    )
    monkeypatch.setitem(REVIEWED_FALLBACKS, "qorvantrix dangling ingredient", target)

    result = match_ingredient(db, "qorvantrix dangling ingredient")
    assert result.method == "manual_review"
    assert result.food.name == "Onions, raw"


def test_validate_reviewed_mappings_flags_missing_food_id(db, monkeypatch):
    target = reviewed("onions raw", "dangling id", food_id=999_999, expected_food_name="Onions, raw")
    monkeypatch.setitem(REVIEWED_FALLBACKS, "qorvantrix dangling ingredient", target)

    diagnostics = validate_reviewed_mappings(db)
    assert any("qorvantrix dangling ingredient" in d and "999999" in d for d in diagnostics)


def test_validate_reviewed_mappings_flags_renamed_food(db, monkeypatch):
    renamed = Food(
        name="Zzyzx Renamed Food, raw", protein_g_per_100g=1.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add(renamed)
    db.commit()

    target = reviewed(
        "irrelevant fallback phrase", "renamed food", food_id=renamed.id, expected_food_name="Zzyzx Original Name, raw",
    )
    monkeypatch.setitem(REVIEWED_FALLBACKS, "qorvantrix renamed ingredient", target)

    diagnostics = validate_reviewed_mappings(db)
    assert any("Zzyzx Original Name, raw" in d and "Zzyzx Renamed Food, raw" in d for d in diagnostics)


def test_validate_reviewed_mappings_silent_when_nothing_pinned(db):
    assert validate_reviewed_mappings(db) == []


# --- prompt section 7: generic muesli composite ---------------------------

def test_muesli_resolves_to_the_generic_composite_not_granola(db):
    """The "muesli" alias used to proxy to homemade granola (a different,
    if adjacent, cereal). It must now resolve to the purpose-built
    composite food instead, even when a granola entry is also present and
    would otherwise be a plausible fuzzy-tier candidate."""
    db.add(Food(
        name="Cereals, granola, homemade", protein_g_per_100g=13.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    ))
    db.add(Food(
        name="Muesli, generic composite (Nutri-Matic estimate)", protein_g_per_100g=9.5,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type=None,
    ))
    db.commit()

    result = match_ingredient(db, "muesli")
    assert result.method == "alias"
    assert result.relationship == "reviewed_substitution"
    assert result.food.name == "Muesli, generic composite (Nutri-Matic estimate)"


def test_validate_reviewed_mappings_silent_when_id_and_name_match(db, monkeypatch):
    pinned = Food(
        name="Zzyzx Stable Food, raw", protein_g_per_100g=1.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add(pinned)
    db.commit()

    target = reviewed("irrelevant fallback phrase", "stable pinned food", food_id=pinned.id, expected_food_name=pinned.name)
    monkeypatch.setitem(REVIEWED_FALLBACKS, "qorvantrix stable ingredient", target)

    assert validate_reviewed_mappings(db) == []
