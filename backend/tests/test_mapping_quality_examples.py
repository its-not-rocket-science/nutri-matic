"""Executable examples of match provenance for each relationship kind —
prompt section 14's deliverable #10 ("examples of API/UI provenance for
an exact alias, a regional equivalent, crumpet as a close analogue, garam
masala as a reviewed substitute, and the new generic muesli
representation"), and section 6's "ordinary exact aliases must not display
alarming proxy warnings" requirement.

Each test exercises the real matcher (food_matching.match_ingredient)
against a small in-memory database built to mirror the real catalog
entries these aliases target, and checks the resulting MatchResult is
exactly what routers/recipes.py forwards into the API's
RecipeIngredientProvenanceOut — the same shape the frontend badge (prompt
section 6) reads relationship/rationale/confidence from."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import match_ingredient


def _db_with(*names: str):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    for name in names:
        session.add(Food(
            name=name, protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
        ))
    session.commit()
    return session


def test_example_exact_alias_no_alarming_warning():
    """"onion" -> "Onions, raw": same food, just reworded. High confidence,
    no fallback, no validation warning — nothing here should read as a
    proxy/approximation to an end user."""
    db = _db_with("Onions, raw")
    result = match_ingredient(db, "onion")

    assert result.method == "alias"
    assert result.relationship == "exact"
    assert result.confidence == 0.95
    assert result.used_fallback is False
    assert result.validation_warning is None
    assert result.food.name == "Onions, raw"


def test_example_regional_equivalent_courgette_zucchini():
    """"courgette" (UK) -> "Squash, summer, zucchini..." (US): a real
    naming difference for the same vegetable, not an approximation."""
    db = _db_with("Squash, summer, zucchini, includes skin, raw")
    result = match_ingredient(db, "courgette")

    assert result.relationship == "regional_equivalent"
    assert result.confidence == 0.93
    assert "zucchini" in result.rationale.lower()


def test_example_close_analogue_crumpet_as_english_muffin():
    """Crumpet has no UK entry in this database at all — English muffins
    (same yeasted-batter griddle-bread class) are the closest specific
    analogue, not a stand-in for a whole missing category."""
    db = _db_with("Muffins, English, plain, enriched, without calcium propionate")
    result = match_ingredient(db, "crumpet")

    assert result.relationship == "close_analogue"
    assert "english muffin" in result.rationale.lower()
    assert "crumpet" in result.rationale.lower()


def test_example_reviewed_substitute_garam_masala_as_curry_powder():
    """No garam masala entry exists in this database at all — curry
    powder (the closest available spice-blend proxy) stands in, at lower
    confidence than an exact/regional match."""
    db = _db_with("Spices, curry powder")
    result = match_ingredient(db, "garam masala")

    assert result.relationship == "category_proxy"
    assert result.confidence < 0.95
    assert "curry powder" in result.rationale.lower()
    assert "garam masala" in result.rationale.lower()


def test_example_generic_muesli_representation():
    """"muesli" now targets the purpose-built composite food (prompt
    section 7), not homemade granola — relationship reviewed_substitution,
    since a maintainer specifically reviewed and built this stand-in
    rather than picking an existing category proxy."""
    db = _db_with(
        "Cereals, granola, homemade",
        "Muesli, generic composite (Nutri-Matic estimate)",
    )
    result = match_ingredient(db, "muesli")

    assert result.food.name == "Muesli, generic composite (Nutri-Matic estimate)"
    assert result.relationship == "reviewed_substitution"
    assert "composite" in result.rationale.lower()
