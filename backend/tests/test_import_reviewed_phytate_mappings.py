"""Tests for app.import_reviewed_phytate_mappings (prompts.txt PROMPT 3
of the phytate/mineral-bioavailability extension) -- the one canonical
reviewed PhyFoodComp ingestion command. Builds a tiny synthetic .xlsx
fixture shaped like the real PhyFoodComp workbook (never the real file
-- see prompts.txt's instruction to keep it out of git/fixtures) plus
review-file and stable-ID-mapping fixtures, so this suite stays
independent of the real workbook's contents and current row counts."""

from datetime import date

import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.import_reviewed_phytate_mappings import (
    ALLOWED_SCOPES,
    DENIED_SCOPES,
    Decision,
    REVIEW_FILES,
    StableTarget,
    apply_plans,
    check_apply_confirmation,
    check_catalogue_drift,
    compute_file_checksum,
    load_review_rows,
    load_stable_id_mapping,
    reconcile_rows,
    validate_and_consolidate,
    validate_scope,
)
from app.models import CompoundObservation, Food
from app.phyfoodcomp_adapter import load_phyfoodcomp_workbook
from app.reference_patterns import AMINO_ACIDS

DATASET_NAME = "PhyFoodComp1.0"
DATASET_CITATION = "FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0."
DATASET_VERSION = "1.0"
ACCESS_DATE = date(2026, 8, 21)

CSV_COLUMNS = [
    "row_identifier", "food_description", "compound_fraction", "value", "candidate",
    "candidate_data_type", "match_confidence", "rationale", "sampled_for_review",
    "review_verdict", "approved_fdc_food", "rejection_reason", "match_scope",
    "reviewer", "review_date", "review_notes",
]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


def _food(**overrides):
    defaults = dict(protein_g_per_100g=10.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
    defaults.update(overrides)
    return Food(**defaults)


def _csv_row(**overrides):
    row = {c: "" for c in CSV_COLUMNS}
    row.update(overrides)
    return row


def _write_review_dir(tmp_path, **file_rows):
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


def _write_stable_id_mapping(tmp_path, rows):
    import csv as csv_module

    path = tmp_path / "stable_id_mapping.csv"
    columns = ["row_identifier", "food_id", "fdc_id", "catalogue_checksum", "approved_fdc_food"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _build_workbook(tmp_path, filename, data_rows, sheet_name="01 Cereals and their products"):
    """data_rows: list of (food_item_id, food_name, prep_code, ip6_value)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["Food item ID", "Food name in English", "Processing / Influencing factors", "IP6(mg)"])
    ws.append(["code", "legend/definitions row -- not data", "legend", "legend"])
    for row in data_rows:
        ws.append(list(row))
    path = tmp_path / filename
    wb.save(path)
    return path


def _decision(rid, verdict, food_description="Test food", compound_fraction="IP6", value=100.0, **overrides):
    defaults = dict(
        row_identifier=rid, verdict=verdict, approved_fdc_food="", candidate_data_type="",
        rationale="test", source_file="test.csv", food_description=food_description,
        compound_fraction=compound_fraction, value=value,
    )
    defaults.update(overrides)
    return Decision(**defaults)


# ---- validate_and_consolidate (unchanged behaviour, now also carrying
# food_description/compound_fraction/value for cross-validation) --------

def test_decision_carries_food_description_and_value_for_cross_validation(tmp_path):
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", food_description="Rice, white", compound_fraction="IP6", value="123.4",
            review_verdict="approve", approved_fdc_food="Food A", candidate="Food A",
            reviewer="Paul S", review_date="16/08/2026", match_scope="category_estimate",
        )],
    })
    decisions, errors, _deferred = validate_and_consolidate(load_review_rows(review_dir))
    assert errors == []
    assert decisions["X:1"].food_description == "Rice, white"
    assert decisions["X:1"].value == 123.4


# ---- reconcile_rows: approve/replace/reject/unresolved -------------------

def test_approve_resolves_fdc_id_from_stable_mapping_not_food_name(session):
    """The stable-ID mapping, not a Food.name lookup, decides the target
    -- required by prompts.txt PROMPT 3: 'must never ... choose an FDC
    target from a food name.'"""
    food = _food(name="Some Branded Product XYZ", data_type="branded_food", fdc_id=999)
    session.add(food)
    session.flush()

    # Built directly as RawObservation (not via the workbook loader), to
    # isolate reconcile_rows from the adapter for this specific assertion.
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "approve")}
    stable_ids = {"1:IP6": StableTarget(food_id=food.id, fdc_id=999, catalogue_checksum="chk")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert report["approved"] == 1
    assert plans[0].fields["matched_food_id"] == food.id
    assert plans[0].fields["match_relationship"] == "close_analogue"


def test_replace_uses_category_proxy_relationship(session):
    from app.ingest_phytate import RawObservation
    food = _food(name="Generic stand-in", fdc_id=555)
    session.add(food)
    session.flush()

    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "replace")}
    stable_ids = {"1:IP6": StableTarget(food_id=food.id, fdc_id=555, catalogue_checksum="chk")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert report["replaced"] == 1
    assert plans[0].fields["match_relationship"] == "category_proxy"


@pytest.mark.parametrize("verdict", ["reject", "unresolved"])
def test_reject_and_unresolved_clear_matched_food_id(session, verdict):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", verdict)}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert plans[0].fields["matched_food_id"] is None
    assert plans[0].fields["match_relationship"] == "needs_review"
    assert plans[0].fields["match_rationale"].startswith("Human-reviewed")
    if verdict == "unresolved":
        assert report["unresolved"] == 1
        assert report["auto_unresolved_censored"] == 0


# ---- blocking problems: fatal, never auto-skipped ------------------------

def test_unknown_row_identifier_is_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="UNKNOWN:IP6",
    )]
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, {}, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert plans == []
    assert report["blocked"] == 1
    assert any("no review verdict" in p for p in problems)


def test_unreviewed_censored_row_is_auto_unresolved_not_blocked(session):
    """CENSORED_ROW_AUTO_POLICY: an unreviewed row_identifier whose
    workbook observation is censored (value=None) must not block the
    entire import -- see module docstring for why this is safe. Also
    covers the bot review finding on PR #52 that a CENSORED_ROW_AUTO_
    POLICY decision must never be persisted with the same 'Human-
    reviewed' rationale prefix a real reviewer's decision gets, and that
    it must not double-count into the mutually-exclusive `unresolved`
    bucket alongside `auto_unresolved_censored`."""
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=None, value_qualifier="below_detection_limit",
        unit="mg", basis="per_100g_edible_portion", compound_fraction="IP6", row_identifier="UNKNOWN:IP6",
    )]
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 1}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, {}, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert report["blocked"] == 0
    assert report["auto_unresolved_censored"] == 1
    assert report["unresolved"] == 0  # mutually exclusive with auto_unresolved_censored, never both
    assert len(plans) == 1
    assert plans[0].fields["matched_food_id"] is None
    assert plans[0].fields["match_relationship"] == "needs_review"

    rationale = plans[0].fields["match_rationale"]
    assert "Human-reviewed" not in rationale
    assert "Auto-classified" in rationale
    assert "not human-reviewed" in rationale
    assert "no review coverage at all" in rationale  # no `deferred` set passed -- genuinely unseen


def test_deferred_censored_row_gets_distinct_rationale_from_truly_unseen(session):
    """Bot review finding: a row a human explicitly looked at and
    deferred (blank verdict + DEFERRED/MOVED note) must not be persisted
    with the same 'no review coverage at all' rationale a row nobody
    ever saw gets -- that would be a false claim about a row someone did
    see. validate_and_consolidate's `deferred` return value is how
    reconcile_rows tells the two apart."""
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=None, value_qualifier="below_detection_limit",
        unit="mg", basis="per_100g_edible_portion", compound_fraction="IP6", row_identifier="X:1",
    )]
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 1}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, {}, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
        deferred={"X:1"},
    )

    assert problems == []
    assert report["auto_unresolved_censored"] == 1
    rationale = plans[0].fields["match_rationale"]
    assert "reviewed but explicitly deferred" in rationale
    assert "no review coverage at all" not in rationale


def test_validate_and_consolidate_tracks_deferred_row_identifiers(tmp_path):
    """A blank-verdict row with a DEFERRED note, never given a real
    verdict anywhere else, must show up in the returned `deferred` set --
    the actual data path reconcile_rows relies on for the distinction
    above."""
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="", review_notes="DEFERRED -- needs a second opinion",
        )],
    })
    decisions, errors, deferred = validate_and_consolidate(load_review_rows(review_dir))
    assert errors == []
    assert "X:1" not in decisions
    assert deferred == {"X:1"}


def test_deferred_row_identifier_is_not_tracked_once_a_real_decision_exists(tmp_path):
    """A row_identifier deferred in one file but given a real verdict in
    another is covered, not deferred -- the real decision wins."""
    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="X:1", review_verdict="", review_notes="DEFERRED -- see review_4",
        )],
        "review_4_special_cases.csv": [_csv_row(
            row_identifier="X:1", review_verdict="reject", candidate="Food A",
            rejection_reason="wrong product form", reviewer="Paul S", review_date="06/08/2026",
        )],
    })
    decisions, errors, deferred = validate_and_consolidate(load_review_rows(review_dir))
    assert errors == []
    assert "X:1" in decisions
    assert deferred == set()


def test_unreviewed_numeric_row_is_still_blocked_not_auto_resolved(session):
    """The auto-policy must never widen past the censored case -- an
    unreviewed row with a real number stays a full blocking problem."""
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="UNKNOWN:IP6",
    )]
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, {}, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert report["auto_unresolved_censored"] == 0
    assert plans == []


def test_duplicate_row_identifier_within_workbook_is_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [
        RawObservation(food_description="Test food", value=100.0, unit="mg",
                        basis="per_100g_edible_portion", compound_fraction="IP6", row_identifier="1:IP6"),
        RawObservation(food_description="Test food", value=100.0, unit="mg",
                        basis="per_100g_edible_portion", compound_fraction="IP6", row_identifier="1:IP6"),
    ]
    decisions = {"1:IP6": _decision("1:IP6", "reject")}
    adapter_stats = {"rows_considered": 2, "observations_built": 2, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert any("duplicate row_identifier" in p for p in problems)


def test_value_mismatch_beyond_tolerance_is_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=999.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "reject", value=100.0)}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert any("disagrees with reviewed record" in p for p in problems)


def test_value_within_float_tolerance_is_not_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.00000001, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "reject", value=100.0)}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert report["blocked"] == 0


def test_food_description_mismatch_is_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Wrong description entirely", value=100.0, unit="mg",
        basis="per_100g_edible_portion", compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "reject", food_description="Test food")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert any("food_description" in p for p in problems)


def test_approve_missing_from_stable_mapping_is_blocked(session):
    from app.ingest_phytate import RawObservation
    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "approve")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, {}, DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert any("stable-ID mapping" in p for p in problems)


def test_stable_mapping_fdc_id_mismatch_with_live_food_row_is_blocked(session):
    """Required by prompts.txt PROMPT 2/3: the importer must verify
    Food.id and fdc_id still refer to the same row, not trust a
    possibly-stale mapping."""
    from app.ingest_phytate import RawObservation
    food = _food(name="Some food", fdc_id=111)  # DB now disagrees with the mapping below
    session.add(food)
    session.flush()

    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "approve")}
    stable_ids = {"1:IP6": StableTarget(food_id=food.id, fdc_id=222, catalogue_checksum="chk")}  # stale fdc_id
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report, problems, plans = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert report["blocked"] == 1
    assert any("stale" in p for p in problems)


# ---- apply confirmation: the second explicit acknowledgement ------------

def test_apply_confirmation_passes_when_both_match():
    assert check_apply_confirmation("1.0", "1.0", "abc", "abc") is None


def test_apply_confirmation_fails_on_dataset_version_mismatch():
    assert check_apply_confirmation("0.9", "1.0", "abc", "abc") is not None


def test_apply_confirmation_fails_on_workbook_checksum_drift():
    """Required by prompts.txt PROMPT 3's test list: 'checksum drift' --
    if the workbook at --xlsx has changed (or is simply the wrong file)
    since the operator confirmed its checksum, --apply must still refuse."""
    assert check_apply_confirmation("1.0", "1.0", "old_checksum", "new_checksum") is not None


def test_apply_confirmation_fails_when_not_supplied_at_all():
    assert check_apply_confirmation(None, "1.0", None, "abc") is not None


# ---- catalogue drift (module-level function, used by main()) ------------

def test_check_catalogue_drift_passes_when_checksums_match():
    stable_ids = {"1:IP6": StableTarget(food_id=1, fdc_id=1, catalogue_checksum="abc")}
    assert check_catalogue_drift(stable_ids, "abc") is None


def test_check_catalogue_drift_flags_mismatch():
    stable_ids = {"1:IP6": StableTarget(food_id=1, fdc_id=1, catalogue_checksum="abc")}
    assert check_catalogue_drift(stable_ids, "different") is not None


def test_check_catalogue_drift_ignores_empty_mapping():
    assert check_catalogue_drift({}, "anything") is None


# ---- import scope gate ----------------------------------------------------

def test_allowed_scope_passes():
    assert validate_scope("noncommercial_free_surface") is None


@pytest.mark.parametrize("scope", sorted(DENIED_SCOPES) + ["totally_unknown_scope", ""])
def test_denied_and_unknown_scopes_are_rejected(scope):
    assert validate_scope(scope) is not None


def test_allowed_scopes_is_exactly_one_value():
    assert ALLOWED_SCOPES == {"noncommercial_free_surface"}


# ---- idempotence, apply, rollback -----------------------------------------

def test_reconcile_rows_never_writes_to_the_database(session):
    from app.ingest_phytate import RawObservation
    food = _food(name="Some food", fdc_id=111)
    session.add(food)
    session.commit()

    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "approve")}
    stable_ids = {"1:IP6": StableTarget(food_id=food.id, fdc_id=111, catalogue_checksum="chk")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )
    session.rollback()

    assert session.query(CompoundObservation).count() == 0


def test_apply_plans_then_reconcile_again_reports_unchanged(session):
    from app.ingest_phytate import RawObservation
    food = _food(name="Some food", fdc_id=111)
    session.add(food)
    session.flush()

    raw_rows = [RawObservation(
        food_description="Test food", value=100.0, unit="mg", basis="per_100g_edible_portion",
        compound_fraction="IP6", row_identifier="1:IP6",
    )]
    decisions = {"1:IP6": _decision("1:IP6", "approve")}
    stable_ids = {"1:IP6": StableTarget(food_id=food.id, fdc_id=111, catalogue_checksum="chk")}
    adapter_stats = {"rows_considered": 1, "observations_built": 1, "censored_observations_built": 0}

    report1, problems1, plans1 = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )
    assert problems1 == []
    assert report1["inserted"] == 1
    apply_plans(session, plans1)
    session.commit()

    report2, problems2, plans2 = reconcile_rows(
        session, raw_rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems2 == []
    assert report2["unchanged"] == 1
    assert report2["inserted"] == 0
    assert session.query(CompoundObservation).count() == 1


def test_error_during_apply_rolls_back_everything(session):
    """Simulates the caller's rollback contract: apply_plans followed by
    a failing commit must leave zero rows, not a partial insert. Plans
    are built by hand (bypassing reconcile_rows, which would have caught
    row 2's problem as 'blocked' instead) to exercise apply_plans' own
    rollback contract directly."""
    good_food = _food(name="Good food", fdc_id=111)
    session.add(good_food)
    session.flush()

    from app.import_reviewed_phytate_mappings import RowPlan
    plans = [
        RowPlan(row_identifier="1:IP6", action="insert", fields=dict(
            compound="phytate", compound_fraction="IP6", original_value=100.0, original_unit="mg",
            original_basis="per_100g_edible_portion", original_value_text="100.0", value_qualifier="measured",
            detection_limit_value=None, detection_limit_unit=None, original_value_provenance="source_reported",
            source_food_description="Test food",
            source_preparation_state=None, source_dataset_name=DATASET_NAME,
            source_dataset_citation=DATASET_CITATION, source_dataset_version=DATASET_VERSION,
            source_access_date=ACCESS_DATE, analytical_method=None, source_row_identifier="1:IP6",
            match_relationship="close_analogue", match_confidence=0.8, match_rationale="test",
            matched_food_id=good_food.id,
        )),
        RowPlan(row_identifier="2:IP5", action="insert", fields=dict(
            compound=None,  # NOT NULL violation -- forces the commit below to fail
            compound_fraction="IP5", original_value=50.0, original_unit="mg",
            original_basis="per_100g_edible_portion", original_value_text="50.0", value_qualifier="measured",
            detection_limit_value=None, detection_limit_unit=None, original_value_provenance="source_reported",
            source_food_description="Test food 2",
            source_preparation_state=None, source_dataset_name=DATASET_NAME,
            source_dataset_citation=DATASET_CITATION, source_dataset_version=DATASET_VERSION,
            source_access_date=ACCESS_DATE, analytical_method=None, source_row_identifier="2:IP5",
            match_relationship="close_analogue", match_confidence=0.8, match_rationale="test",
            matched_food_id=None,
        )),
    ]

    apply_plans(session, plans)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()

    assert session.query(CompoundObservation).count() == 0


# ---- no automated/fuzzy matching -------------------------------------------

def test_module_never_imports_fuzzy_food_matching():
    import app.import_reviewed_phytate_mappings as m
    assert not hasattr(m, "match_ingredient")
    assert "stock_recipes" not in (m.__dict__.get("food_matching", "") or "")


# ---- file helpers ----------------------------------------------------------

def test_load_stable_id_mapping_reads_expected_columns(tmp_path):
    path = _write_stable_id_mapping(tmp_path, [
        {
            "row_identifier": "1:IP6", "food_id": "5", "fdc_id": "12345", "catalogue_checksum": "abc",
            "approved_fdc_food": "Wheat flour, white",
        },
    ])
    mapping = load_stable_id_mapping(path)
    assert mapping["1:IP6"] == StableTarget(
        food_id=5, fdc_id=12345, catalogue_checksum="abc", approved_fdc_food="Wheat flour, white",
    )


def test_compute_file_checksum_is_deterministic(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello world")
    assert compute_file_checksum(path) == compute_file_checksum(path)


def test_compute_file_checksum_changes_with_content(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello world")
    checksum1 = compute_file_checksum(path)
    path.write_bytes(b"hello world!")
    checksum2 = compute_file_checksum(path)
    assert checksum1 != checksum2


# ---- real (synthetic) workbook end-to-end ----------------------------------

def test_real_synthetic_workbook_reconciles_end_to_end(session, tmp_path):
    food = _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=777)
    session.add(food)
    session.flush()

    workbook = _build_workbook(tmp_path, "wb.xlsx", [("42", "Rice, white cooked", "r", 250.5)])
    rows, adapter_stats = load_phyfoodcomp_workbook(workbook)
    assert len(rows) == 1
    assert rows[0].row_identifier == "42:IP6"

    review_dir = _write_review_dir(tmp_path, **{
        "review_1_ambiguous.csv": [_csv_row(
            row_identifier="42:IP6", food_description="Rice, white cooked", compound_fraction="IP6", value="250.5",
            review_verdict="approve", approved_fdc_food="Rice, white", candidate="Rice, white",
            candidate_data_type="sr_legacy_food", reviewer="Paul S", review_date="21/08/2026",
            match_scope="category_estimate",
        )],
    })
    decisions, errors, _deferred = validate_and_consolidate(load_review_rows(review_dir))
    assert errors == []

    stable_ids = {"42:IP6": StableTarget(food_id=food.id, fdc_id=777, catalogue_checksum="chk")}

    report, problems, plans = reconcile_rows(
        session, rows, adapter_stats, decisions, stable_ids,
        DATASET_NAME, DATASET_CITATION, DATASET_VERSION, ACCESS_DATE,
    )

    assert problems == []
    assert report["approved"] == 1
    assert report["inserted"] == 1
    apply_plans(session, plans)
    session.commit()

    saved = session.query(CompoundObservation).one()
    assert saved.matched_food_id == food.id
    assert saved.original_value == 250.5
