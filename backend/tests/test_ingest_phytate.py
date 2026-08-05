"""Tests for app.ingest_phytate (prompts.txt Prompt 3 of the phytate/
mineral-bioavailability extension) — match-confidence assignment against
the stated rules, needs-review flagging (including a deliberately
ambiguous fixture case), and idempotent re-ingestion. Exercises the app's
real food-matching infrastructure (match_ingredient/search_foods_by_name)
against a small in-memory SQLite Food set, not a mocked matcher — the
point is testing these classification rules against how matching
actually behaves.

No real PhyFoodComp data here — see ingest_phytate's module docstring on
why (licence unresolved, docs/phytate-evidence-review.md). All fixtures
below are invented."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.ingest_phytate import RawObservation, classify_match, ingest_rows, load_rows
from app.models import CompoundObservation, Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import match_ingredient


def _food(**overrides):
    defaults = dict(protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    defaults.update(overrides)
    return Food(**defaults)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


DATASET_KWARGS = dict(
    dataset_name="PhyFoodComp1.0",
    dataset_citation="FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0.",
    dataset_version="1.0",
    access_date=date(2026, 8, 1),
)


def _row(**overrides):
    defaults = dict(
        food_description="Wheat flour, whole grain", value=250.0, unit="mg", basis="per_100g_edible_portion",
    )
    defaults.update(overrides)
    return RawObservation(**defaults)


# ---- load_rows -------------------------------------------------------

def test_load_rows_parses_required_and_optional_columns(tmp_path):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "food_description,value,unit,basis,preparation_state,compound_fraction,analytical_method,row_identifier\n"
        "Wheat flour,250,mg,per_100g_edible_portion,raw,IP6,HPLC,PFC-001\n"
        "Chickpeas,180,mg,per_100g_edible_portion,,,,\n",
        encoding="utf-8",
    )
    rows = load_rows(csv_path)
    assert len(rows) == 2
    assert rows[0] == RawObservation(
        food_description="Wheat flour", value=250.0, unit="mg", basis="per_100g_edible_portion",
        preparation_state="raw", compound_fraction="IP6", analytical_method="HPLC", row_identifier="PFC-001",
    )
    assert rows[1].preparation_state is None
    assert rows[1].compound_fraction is None
    assert rows[1].row_identifier is None


# ---- classify_match ----------------------------------------------------

def test_classify_match_no_candidate_is_needs_review(session):
    match = match_ingredient(session, "Nonexistent Made Up Food Xyz")
    relationship, rationale = classify_match(
        session, match, "Nonexistent Made Up Food Xyz", None, "per_100g_edible_portion",
    )
    assert relationship == "needs_review"
    assert "no FDC candidate" in rationale


def test_classify_match_low_confidence_branded_fuzzy_match_is_needs_review(session):
    # brand-prefixed, like real branded foods (see ingest_fdc.py), so this
    # doesn't also satisfy the canonical-lookup prefix match and skip the
    # fuzzy tier entirely.
    session.add(_food(name="XyzCo Some Distant Fuzzy Branded Product", data_type="branded_food"))
    session.commit()
    match = match_ingredient(session, "Some Distant Fuzzy Branded Product")
    assert match.method == "fuzzy"
    relationship, rationale = classify_match(
        session, match, "Some Distant Fuzzy Branded Product", None, "per_100g_edible_portion",
    )
    assert relationship == "needs_review"
    assert "confidence" in rationale


def test_classify_match_prep_state_and_edible_basis_is_regional_equivalent(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, rationale = classify_match(
        session, match, "Wheat flour, whole grain", "raw", "per_100g_edible_portion",
    )
    assert relationship == "regional_equivalent"
    assert "raw" in rationale


def test_classify_match_no_prep_state_is_close_analogue_not_exact(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(session, match, "Wheat flour, whole grain", None, "per_100g_edible_portion")
    assert relationship == "close_analogue"


def test_classify_match_dry_matter_basis_never_reaches_regional_equivalent(session):
    """Even with a matching preparation state, a dry-matter original basis
    (not yet normalised to edible portion) must not be treated as
    confirmed-aligned — see Prompt 2's original_basis field."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(session, match, "Wheat flour, whole grain", "raw", "per_100g_dry_matter")
    assert relationship != "regional_equivalent"


@pytest.mark.parametrize("preparation_state,basis", [
    (None, "per_100g_edible_portion"),
    ("raw", "per_100g_edible_portion"),
    ("raw", "per_100g_dry_matter"),
    (None, "per_100g_dry_matter"),
])
def test_classify_match_never_returns_exact(session, preparation_state, basis):
    """Automated matching must never assign "exact" — reserved for a
    human-verified mapping this script has no way to produce on its own."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()
    match = match_ingredient(session, "Wheat flour, whole grain")
    relationship, _ = classify_match(session, match, "Wheat flour, whole grain", preparation_state, basis)
    assert relationship != "exact"


def test_classify_match_ambiguous_candidates_is_needs_review(session):
    """The deliberately-ambiguous fixture case: two foods differing only
    by a detail the description doesn't specify, similarly matching the
    query — must be flagged for a human, not silently resolved to
    whichever the matcher happens to rank first."""
    session.add(_food(name="Beans, kidney, red, mature seeds, raw"))
    session.add(_food(name="Beans, kidney, white, mature seeds, raw"))
    session.commit()
    match = match_ingredient(session, "Beans, kidney")
    relationship, rationale = classify_match(session, match, "Beans, kidney", None, "per_100g_edible_portion")
    assert relationship == "needs_review"
    assert "too textually similar" in rationale


# ---- ingest_rows ---------------------------------------------------------

def test_ingest_rows_end_to_end_counts_and_needs_review_sample(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.add(_food(name="Beans, kidney, red, mature seeds, raw"))
    session.add(_food(name="Beans, kidney, white, mature seeds, raw"))
    session.commit()

    rows = [
        _row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001"),
        _row(food_description="Beans, kidney", row_identifier="PFC-002"),
    ]
    stats, samples = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert stats == {"considered": 2, "inserted": 2, "updated": 0, "needs_review": 1}
    assert len(samples) == 1
    assert samples[0]["food_description"] == "Beans, kidney"

    observations = {o.source_row_identifier: o for o in session.query(CompoundObservation).all()}
    assert observations["PFC-001"].match_relationship == "regional_equivalent"
    assert observations["PFC-002"].match_relationship == "needs_review"


def test_reingesting_the_same_rows_is_idempotent(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001")]
    stats1, _ = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)
    stats2, _ = ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert stats1["inserted"] == 1
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 1
    assert session.query(CompoundObservation).count() == 1


def test_rows_without_row_identifier_are_always_inserted(session):
    """No natural key to dedupe on — see uq_compound_observation_source_row
    (Prompt 2). A source with no native row identifier needs its own
    dedup strategy; this script's job is just not to silently corrupt
    what it can't tell apart."""
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier=None)]
    ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)
    ingest_rows(session, rows, dry_run=False, **DATASET_KWARGS)

    assert session.query(CompoundObservation).count() == 2


def test_dry_run_does_not_write_to_the_database(session):
    session.add(_food(name="Wheat flour, whole grain, raw"))
    session.commit()

    rows = [_row(food_description="Wheat flour, whole grain", preparation_state="raw", row_identifier="PFC-001")]
    stats, _ = ingest_rows(session, rows, dry_run=True, **DATASET_KWARGS)

    assert stats["considered"] == 1  # classified, but nothing actually persisted
    assert stats["inserted"] == 0
    assert session.query(CompoundObservation).count() == 0
