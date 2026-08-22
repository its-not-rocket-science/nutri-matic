"""Tests for app.import_reviewed_phytate_mappings (prompts.txt PROMPT 3C)
— applying human-reviewed review_*.csv verdicts to CompoundObservation
rows already created by ingest_phytate.py. Builds review-file fixtures
directly (not the real review CSVs) so this suite stays independent of
their exact current row counts."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.import_reviewed_phytate_mappings import (
    REVIEW_FILES,
    apply_reviewed_mappings,
    load_review_rows,
    validate_and_consolidate,
)
from app.models import CompoundObservation, Food
from app.reference_patterns import AMINO_ACIDS

DATASET_NAME = "PhyFoodComp1.0"
DATASET_VERSION = "1.0"

CSV_COLUMNS = [
    "row_identifier", "food_description", "compound_fraction", "value", "candidate",
    "candidate_data_type", "match_confidence", "rationale", "sampled_for_review",
    "review_verdict", "approved_fdc_food", "rejection_reason", "match_scope",
    "reviewer", "review_date", "review_notes",
]


def _csv_row(**overrides):
    row = {c: "" for c in CSV_COLUMNS}
    row.update(overrides)
    return row


def _write_review_dir(tmp_path, **file_rows):
    """Writes every file in REVIEW_FILES (empty-but-headered by default,
    so load_review_rows doesn't fail on a missing file), overriding
    specific files' contents with file_rows[filename] = [row, ...]."""
    import csv as csv_module

    review_dir = tmp_path / "review"
    review_dir.mkdir()
    for fname in REVIEW_FILES:
        rows = file_rows.get(fname, [])
        with open(review_dir / fname, "w", newline="", encoding="utf-8") as f:
            writer = csv_module.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
    return review_dir


def _food(**overrides):
    defaults = dict(protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    defaults.update(overrides)
    return Food(**defaults)


def _observation(**overrides):
    defaults = dict(
        compound="phytate", original_value=100.0, original_unit="mg",
        original_basis="per_100g_edible_portion", source_food_description="Test food",
        source_dataset_name=DATASET_NAME, source_dataset_citation="Test citation",
        source_dataset_version=DATASET_VERSION, source_access_date=date(2026, 8, 1),
        match_relationship="needs_review",
    )
    defaults.update(overrides)
    return CompoundObservation(**defaults)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


# ---- validate_and_consolidate -----------------------------------------

def test_blank_verdict_without_explanation_is_a_blocking_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(row_identifier="X:1", review_verdict="")],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert any("blank review_verdict" in e for e in errors)


def test_blank_verdict_with_moved_note_is_not_an_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(row_identifier="X:1", review_verdict="", review_notes="MOVED -- see review_4")],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert errors == []


def test_blank_verdict_with_sampled_for_review_no_is_not_an_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_3_branded_low_confidence.csv": [
            _csv_row(row_identifier="X:1", review_verdict="", sampled_for_review="NO"),
        ],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert errors == []


def test_approve_missing_match_scope_is_a_blocking_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="approve", approved_fdc_food="Food A",
            candidate="Food A", reviewer="Paul S", review_date="16/08/2026", match_scope="",
        )],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert any("match_scope is blank" in e for e in errors)


def test_approve_missing_reviewer_is_a_blocking_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="approve", approved_fdc_food="Food A",
            candidate="Food A", reviewer="", match_scope="category_estimate",
        )],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert any("no reviewer sign-off" in e for e in errors)


def test_contradictory_verdicts_not_superseded_is_a_blocking_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="approve", approved_fdc_food="Food A",
            candidate="Food A", reviewer="Paul S", review_date="16/08/2026", match_scope="category_estimate",
        )],
        "review_4_special_cases.csv": [_csv_row(
            row_identifier="X:1", review_verdict="reject", candidate="Food A",
            rejection_reason="wrong product form", reviewer="Paul S", review_date="06/08/2026",
        )],
    })
    rows_by_file = load_review_rows(review_dir)
    _, errors = validate_and_consolidate(rows_by_file)
    assert any("contradicted by" in e for e in errors)


def test_contradictory_verdict_flagged_superseded_is_not_an_error(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="approve", approved_fdc_food="Food A",
            candidate="Food A", reviewer="Paul S", review_date="16/08/2026", match_scope="category_estimate",
            review_notes="MOVED -- superseded by review_4",
        )],
        "review_4_special_cases.csv": [_csv_row(
            row_identifier="X:1", review_verdict="reject", candidate="Food A",
            rejection_reason="wrong product form", reviewer="Paul S", review_date="06/08/2026",
        )],
    })
    rows_by_file = load_review_rows(review_dir)
    decisions, errors = validate_and_consolidate(rows_by_file)
    assert errors == []
    assert decisions["X:1"].verdict == "reject"


# ---- apply_reviewed_mappings --------------------------------------------

def test_approve_sets_close_analogue_and_keeps_existing_matched_food(session):
    food = _food(name="Existing match")
    session.add(food)
    session.flush()
    obs = _observation(source_row_identifier="X:1", matched_food_id=food.id, match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {
        "X:1": _decision("X:1", "approve", "Existing match", "sr_legacy_food", "Good match"),
    }
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    session.refresh(obs)
    assert obs.matched_food_id == food.id
    assert obs.match_relationship == "close_analogue"
    assert obs.match_confidence == 0.8
    assert stats["approved"] == 1


def test_replace_looks_up_new_food_by_name_and_sets_category_proxy(session):
    old_food = _food(name="Wrong match")
    new_food = _food(name="Right match", data_type="sr_legacy_food")
    session.add_all([old_food, new_food])
    session.flush()
    obs = _observation(source_row_identifier="X:1", matched_food_id=old_food.id, match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {
        "X:1": _decision("X:1", "replace", "Right match", "sr_legacy_food", "Better match found"),
    }
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    session.refresh(obs)
    assert obs.matched_food_id == new_food.id
    assert obs.match_relationship == "category_proxy"
    assert obs.match_confidence == 0.65
    assert stats["replaced"] == 1


def test_reject_genuinely_clears_matched_food_id_not_just_flags_it(session):
    """Required by prompts.txt PROMPT 3C's own test list: confirms the
    FK is actually nulled, not left standing with only match_relationship
    changed."""
    food = _food(name="Wrong match")
    session.add(food)
    session.flush()
    obs = _observation(source_row_identifier="X:1", matched_food_id=food.id, match_relationship="close_analogue")
    session.add(obs)
    session.commit()

    decisions = {
        "X:1": _decision("X:1", "reject", "", "", "Wrong product form"),
    }
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    session.refresh(obs)
    assert obs.matched_food_id is None
    assert obs.match_relationship == "needs_review"
    assert obs.match_confidence is None
    assert stats["rejected"] == 1


def test_unresolved_also_clears_matched_food_id(session):
    obs = _observation(source_row_identifier="X:1", matched_food_id=None, match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {
        "X:1": _decision("X:1", "unresolved", "", "", "No FDC candidate found"),
    }
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    session.refresh(obs)
    assert obs.matched_food_id is None
    assert obs.match_relationship == "needs_review"
    assert stats["rejected"] == 1


def test_approve_and_replace_use_different_match_relationship_values(session):
    """Required by prompts.txt PROMPT 3C requirement 1: approve and
    replace must not collapse to the same match_relationship."""
    food_a = _food(name="Match A")
    food_b = _food(name="Match B", data_type="sr_legacy_food")
    session.add_all([food_a, food_b])
    session.flush()
    obs_a = _observation(source_row_identifier="A:1", matched_food_id=food_a.id, match_relationship="needs_review")
    obs_b = _observation(source_row_identifier="B:1", matched_food_id=food_a.id, match_relationship="needs_review")
    session.add_all([obs_a, obs_b])
    session.commit()

    decisions = {
        "A:1": _decision("A:1", "approve", "Match A", "", "Good"),
        "B:1": _decision("B:1", "replace", "Match B", "sr_legacy_food", "Better"),
    }
    apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    session.refresh(obs_a)
    session.refresh(obs_b)
    assert obs_a.match_relationship != obs_b.match_relationship


def test_row_identifier_not_in_database_is_reported_not_fatal(session):
    decisions = {"NOPE:1": _decision("NOPE:1", "approve", "Food A", "", "Good")}
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)
    assert stats["not_found"] == 1
    assert stats["approved"] == 0


def test_replace_target_food_not_found_is_reported_not_fatal(session):
    obs = _observation(source_row_identifier="X:1", match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {"X:1": _decision("X:1", "replace", "Nonexistent food", "", "Better")}
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    assert stats["food_not_found"] == 1
    assert stats["replaced"] == 0


def test_dry_run_does_not_commit(session):
    food = _food(name="Existing match")
    session.add(food)
    session.flush()
    obs = _observation(source_row_identifier="X:1", matched_food_id=food.id, match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {"X:1": _decision("X:1", "reject", "", "", "Wrong")}
    apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=True)
    session.rollback()

    reloaded = session.query(CompoundObservation).filter_by(source_row_identifier="X:1").one()
    assert reloaded.matched_food_id == food.id
    assert reloaded.match_relationship == "needs_review"


def test_reapplying_the_same_decisions_is_idempotent(session):
    food = _food(name="Existing match")
    session.add(food)
    session.flush()
    obs = _observation(source_row_identifier="X:1", matched_food_id=food.id, match_relationship="needs_review")
    session.add(obs)
    session.commit()

    decisions = {"X:1": _decision("X:1", "approve", "Existing match", "", "Good")}
    apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)
    apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    assert session.query(CompoundObservation).count() == 1
    reloaded = session.query(CompoundObservation).filter_by(source_row_identifier="X:1").one()
    assert reloaded.match_relationship == "close_analogue"


def test_still_needs_review_counts_observations_no_decision_covers(session):
    food = _food(name="Match A")
    session.add(food)
    session.flush()
    covered = _observation(source_row_identifier="X:1", matched_food_id=food.id, match_relationship="needs_review")
    uncovered = _observation(source_row_identifier="Y:1", matched_food_id=None, match_relationship="needs_review")
    session.add_all([covered, uncovered])
    session.commit()

    decisions = {"X:1": _decision("X:1", "approve", "Match A", "", "Good")}
    stats = apply_reviewed_mappings(session, decisions, DATASET_NAME, DATASET_VERSION, dry_run=False)

    assert stats["still_needs_review"] == 1


def _decision(row_identifier, verdict, approved_fdc_food, candidate_data_type, rationale):
    from app.import_reviewed_phytate_mappings import Decision
    return Decision(
        row_identifier=row_identifier, verdict=verdict, approved_fdc_food=approved_fdc_food,
        candidate_data_type=candidate_data_type, rationale=rationale, source_file="test.csv",
    )
