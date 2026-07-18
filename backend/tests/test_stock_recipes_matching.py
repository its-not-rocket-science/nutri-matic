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
from app.stock_recipes.food_matching import compute_coverage, match_ingredient, normalise_ingredient_name


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
