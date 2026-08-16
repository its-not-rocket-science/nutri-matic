"""Schema-only tests for CompoundObservation (prompts.txt Prompt 2 of the
phytate/mineral-bioavailability extension) — constraints and nullability,
no ingestion logic yet (that's Prompt 3). Uses an in-memory SQLite
database built straight from Base.metadata, same convention as
test_recipe_provenance.py, rather than the real Postgres fixture other
migration tests use — nothing here depends on a Postgres-only feature."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CompoundObservation, Food
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


def _minimal_kwargs(**overrides):
    """The required-by-schema field set (everything NOT NULL on
    CompoundObservation), as a dict so individual tests can omit/override
    one field at a time to probe nullability."""
    kwargs = dict(
        compound="phytate",
        original_value=250.0,
        original_unit="mg",
        original_basis="per_100g_edible_portion",
        source_food_description="Wheat flour, whole grain",
        source_dataset_name="PhyFoodComp1.0",
        source_dataset_citation="FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0.",
        source_dataset_version="1.0",
        source_access_date=date(2026, 8, 1),
        match_relationship="needs_review",
    )
    kwargs.update(overrides)
    return kwargs


def test_minimal_observation_with_no_fdc_match_persists(session):
    """Ground rules: an observation with no confident FDC match must
    still be storable, not discarded."""
    obs = CompoundObservation(**_minimal_kwargs())
    session.add(obs)
    session.commit()

    saved = session.query(CompoundObservation).one()
    assert saved.matched_food_id is None
    assert saved.match_relationship == "needs_review"
    assert saved.compound_fraction is None
    assert saved.normalised_value is None


@pytest.mark.parametrize("required_field", [
    "compound", "original_value", "original_unit", "original_basis",
    "source_food_description", "source_dataset_name", "source_dataset_citation",
    "source_dataset_version", "source_access_date", "match_relationship",
])
def test_required_field_cannot_be_null(session, required_field):
    kwargs = _minimal_kwargs(**{required_field: None})
    session.add(CompoundObservation(**kwargs))
    with pytest.raises(Exception):  # IntegrityError, wrapped by whichever DBAPI driver SQLite uses here
        session.commit()
    session.rollback()


@pytest.mark.parametrize("optional_field,value", [
    ("compound_fraction", "IP6"),
    ("source_preparation_state", "raw"),
    ("analytical_method", "HPLC"),
    ("source_row_identifier", "PFC-00123"),
    ("match_confidence", 0.4),
    ("match_rationale", "same species, different cultivar"),
])
def test_optional_field_can_be_omitted_or_set(session, optional_field, value):
    omitted = CompoundObservation(**_minimal_kwargs())
    session.add(omitted)
    session.commit()
    assert getattr(omitted, optional_field) is None

    session.rollback()
    populated = CompoundObservation(**_minimal_kwargs(**{optional_field: value}))
    session.add(populated)
    session.commit()
    assert getattr(populated, optional_field) == value


def test_match_relationship_rejects_values_outside_the_shared_vocabulary(session):
    """Reuses RecipeIngredientProvenance's AliasRelationship vocabulary
    plus "needs_review" — see the CheckConstraint's comment in models.py.
    A sixth, invented value must fail loudly rather than silently widen
    what "confidence" means for this table."""
    obs = CompoundObservation(**_minimal_kwargs(match_relationship="probably_fine"))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("relationship", [
    "exact", "regional_equivalent", "close_analogue", "category_proxy", "needs_review",
])
def test_match_relationship_accepts_every_shared_vocabulary_value(session, relationship):
    obs = CompoundObservation(**_minimal_kwargs(match_relationship=relationship))
    session.add(obs)
    session.commit()
    assert obs.match_relationship == relationship


@pytest.mark.parametrize("partial_fields", [
    {"normalised_value": 42.0},
    {"normalised_unit": "mg"},
    {"normalised_basis": "per_100g_edible_portion"},
    {"normalised_value": 42.0, "normalised_unit": "mg"},
    {"normalisation_method": "converted from dry matter"},
    {
        "normalised_value": 42.0, "normalised_unit": "mg",
        "normalised_basis": "per_100g_edible_portion",
    },
])
def test_normalised_triple_rejects_partial_values(session, partial_fields):
    obs = CompoundObservation(**_minimal_kwargs(**partial_fields))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_normalised_triple_accepts_all_three_together(session):
    obs = CompoundObservation(**_minimal_kwargs(
        original_basis="per_100g_dry_matter",
        normalised_value=42.0,
        normalised_unit="mg",
        normalised_basis="per_100g_edible_portion",
        normalisation_method="converted from dry matter using source-reported moisture content of 11.2%",
    ))
    session.add(obs)
    session.commit()
    assert obs.normalised_value == 42.0
    assert obs.normalisation_method is not None


def test_normalised_triple_accepts_all_none_together(session):
    obs = CompoundObservation(**_minimal_kwargs())
    session.add(obs)
    session.commit()
    assert obs.normalised_value is None
    assert obs.normalised_unit is None
    assert obs.normalised_basis is None
    assert obs.normalisation_method is None


def test_duplicate_source_row_identifier_is_rejected(session):
    """Backs Prompt 3's idempotent-re-ingestion requirement: the same
    source row, re-ingested, must not duplicate an observation."""
    session.add(CompoundObservation(**_minimal_kwargs(source_row_identifier="PFC-00123")))
    session.commit()

    session.add(CompoundObservation(**_minimal_kwargs(source_row_identifier="PFC-00123")))
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_duplicate_null_source_row_identifier_is_allowed(session):
    """Standard SQL unique-constraint semantics: multiple NULLs don't
    conflict. Sources with no native row identifier need their own dedup
    strategy in the ingestion script (Prompt 3) — not this constraint's job."""
    session.add(CompoundObservation(**_minimal_kwargs(source_row_identifier=None)))
    session.add(CompoundObservation(**_minimal_kwargs(source_row_identifier=None)))
    session.commit()

    assert session.query(CompoundObservation).count() == 2


def test_different_dataset_version_reuses_the_same_row_identifier(session):
    """A new dataset release re-using the source's own row identifiers
    must not collide with the previous version's observations — the
    unique constraint is scoped per (compound, dataset, version)."""
    session.add(CompoundObservation(**_minimal_kwargs(
        source_dataset_version="1.0", source_row_identifier="PFC-00123",
    )))
    session.add(CompoundObservation(**_minimal_kwargs(
        source_dataset_version="1.1", source_row_identifier="PFC-00123",
    )))
    session.commit()

    assert session.query(CompoundObservation).count() == 2


def test_matched_food_id_links_to_a_real_food_row(session):
    food = Food(name="Wheat flour, whole grain", protein_g_per_100g=13.2, amino_acids=dict.fromkeys(AMINO_ACIDS))
    session.add(food)
    session.flush()

    obs = CompoundObservation(**_minimal_kwargs(
        match_relationship="close_analogue", match_confidence=0.8, matched_food_id=food.id,
    ))
    session.add(obs)
    session.commit()

    saved = session.query(CompoundObservation).one()
    assert saved.matched_food_id == food.id
