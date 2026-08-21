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
        original_value_text="250.0",
        value_qualifier="measured",
        original_value_provenance="source_reported",
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
    "compound", "original_unit", "original_basis", "original_value_text", "value_qualifier",
    "source_food_description", "source_dataset_name", "source_dataset_citation",
    "source_dataset_version", "source_access_date", "match_relationship",
])
def test_required_field_cannot_be_null(session, required_field):
    kwargs = _minimal_kwargs(**{required_field: None})
    session.add(CompoundObservation(**kwargs))
    with pytest.raises(Exception):  # IntegrityError, wrapped by whichever DBAPI driver SQLite uses here
        session.commit()
    session.rollback()


# ---- Prompt 5 (prompts.txt): censored/non-numeric value preservation ----

def test_original_value_can_be_null_for_a_censored_observation(session):
    """Unlike the fields in test_required_field_cannot_be_null above,
    original_value became nullable in Prompt 5 -- a censored observation
    has no number to store."""
    obs = CompoundObservation(**_minimal_kwargs(
        original_value=None, original_value_provenance=None, value_qualifier="below_detection_limit",
        original_value_text="< LOD",
    ))
    session.add(obs)
    session.commit()
    assert obs.original_value is None


def test_value_qualifier_rejects_values_outside_the_shared_vocabulary(session):
    obs = CompoundObservation(**_minimal_kwargs(value_qualifier="probably_censored"))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("qualifier", [
    "measured", "reported_zero", "below_detection_limit", "below_quantification_limit",
    "trace", "not_reported", "unparseable",
])
def test_value_qualifier_accepts_every_shared_vocabulary_value(session, qualifier):
    is_numeric_backed = qualifier in ("measured", "reported_zero")
    obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier=qualifier,
        original_value=250.0 if is_numeric_backed else None,
        original_value_provenance="source_reported" if is_numeric_backed else None,
        original_value_text="250.0" if is_numeric_backed else "< LOD",
    ))
    session.add(obs)
    session.commit()
    assert obs.value_qualifier == qualifier


@pytest.mark.parametrize("qualifier,original_value,provenance", [
    ("measured", None, None),  # measured but no number at all
    ("measured", 250.0, None),  # measured number but no provenance recorded
    ("below_detection_limit", 250.0, "source_reported"),  # censored qualifier but a number snuck in
    ("below_detection_limit", None, "source_reported"),  # censored qualifier but a provenance snuck in
])
def test_value_qualifier_and_original_value_pairing_is_enforced(session, qualifier, original_value, provenance):
    """Required by prompts.txt PROMPT 5: a censored qualifier and a real
    number must never coexist on the same row, in either direction."""
    obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier=qualifier, original_value=original_value, original_value_provenance=provenance,
        original_value_text="250.0" if original_value is not None else "< LOD",
    ))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_original_value_provenance_rejects_values_outside_the_shared_vocabulary(session):
    obs = CompoundObservation(**_minimal_kwargs(original_value_provenance="guessed"))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("provenance", ["source_reported", "converted", "imputed"])
def test_original_value_provenance_accepts_every_shared_vocabulary_value(session, provenance):
    obs = CompoundObservation(**_minimal_kwargs(original_value_provenance=provenance))
    session.add(obs)
    session.commit()
    assert obs.original_value_provenance == provenance


@pytest.mark.parametrize("partial_fields", [
    {"detection_limit_value": 0.5},
    {"detection_limit_unit": "mg"},
])
def test_detection_limit_rejects_partial_values(session, partial_fields):
    obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier="below_detection_limit", original_value=None, original_value_provenance=None,
        original_value_text="< LOD", **partial_fields,
    ))
    session.add(obs)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_detection_limit_accepts_both_together_when_source_states_one(session):
    obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier="below_detection_limit", original_value=None, original_value_provenance=None,
        original_value_text="< 0.5 mg", detection_limit_value=0.5, detection_limit_unit="mg",
    ))
    session.add(obs)
    session.commit()
    assert obs.detection_limit_value == 0.5


def test_detection_limit_accepts_neither_when_source_states_none(session):
    obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier="below_detection_limit", original_value=None, original_value_provenance=None,
        original_value_text="< LOD",
    ))
    session.add(obs)
    session.commit()
    assert obs.detection_limit_value is None
    assert obs.detection_limit_unit is None


def test_a_literal_reported_zero_is_distinct_from_below_detection_limit(session):
    """Required by prompts.txt PROMPT 5: 'a literal reported zero remains
    distinct from absent or below-LOD.'"""
    zero_obs = CompoundObservation(**_minimal_kwargs(
        value_qualifier="reported_zero", original_value=0.0, original_value_text="0.0",
    ))
    session.add(zero_obs)
    session.commit()
    assert zero_obs.original_value == 0.0
    assert zero_obs.value_qualifier == "reported_zero"


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
