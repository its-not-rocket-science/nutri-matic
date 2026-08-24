"""Tests for app.validate_stable_id_mapping (prompts.txt PROMPT 12) --
offline structural validation of the stable-ID mapping artifact, and the
mapping-integrity digest. Uses only synthetic fixtures/fabricated rows;
never reads the real private mapping file, matching PROMPT 12's own
requirement that ordinary public CI needs neither the real FDC catalogue
nor real PhyFoodComp artifacts."""

import csv
from pathlib import Path

from app.resolve_phytate_stable_ids import MAPPING_OUT_COLUMNS
from app.validate_stable_id_mapping import (
    compute_mapping_integrity_digest,
    validate_structure,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_MAPPING = FIXTURES_DIR / "synthetic_stable_id_mapping.csv"


def _row(**overrides):
    defaults = dict(
        row_identifier="1:IP6", food_description="Test food", compound_fraction="IP6", value="10.0",
        food_id="1", fdc_id="100001", approved_fdc_food="Test Food, raw", data_type="sr_legacy_food",
        review_verdict="approve", match_scope="category_estimate", reviewer="Test Reviewer",
        review_date="01/01/2026", review_notes="", catalogue_checksum="abc123",
    )
    defaults.update(overrides)
    return defaults


# ---- the real synthetic fixture, loaded from disk --------------------------

def test_synthetic_fixture_passes_structural_validation():
    with open(SYNTHETIC_MAPPING, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert validate_structure(rows) == []


def test_synthetic_fixture_columns_match_the_real_schema():
    """Requirement 5: CI must fail if the mapping schema changes without
    the fixture being updated to match -- enforced by importing the real
    schema constant directly, not duplicating a second copy of it."""
    with open(SYNTHETIC_MAPPING, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    assert header == MAPPING_OUT_COLUMNS


# ---- validate_structure: hand-built cases -----------------------------------

def test_empty_mapping_is_a_problem():
    assert validate_structure([]) != []


def test_missing_column_is_reported_and_stops_further_checks():
    row = _row()
    del row["match_scope"]
    problems = validate_structure([row])
    assert len(problems) == 1
    assert "match_scope" in problems[0]


def test_duplicate_row_identifier_is_a_problem():
    problems = validate_structure([_row(row_identifier="1:IP6"), _row(row_identifier="1:IP6")])
    assert any("duplicate row_identifier" in p for p in problems)


def test_non_numeric_food_id_is_a_problem():
    problems = validate_structure([_row(food_id="not-a-number")])
    assert any("food_id" in p for p in problems)


def test_non_numeric_fdc_id_is_a_problem():
    problems = validate_structure([_row(fdc_id="not-a-number")])
    assert any("fdc_id" in p for p in problems)


def test_reject_verdict_is_never_allowed_in_a_stable_mapping():
    """A stable-ID mapping row is by definition already resolved to a
    target -- a reject/unresolved verdict should never appear here at
    all (resolve_mapping_rows never emits one), so its presence is a
    structural inconsistency, not a normal state."""
    problems = validate_structure([_row(review_verdict="reject")])
    assert any("review_verdict" in p for p in problems)


def test_blank_match_scope_is_a_problem():
    problems = validate_structure([_row(match_scope="")])
    assert any("match_scope is blank" in p for p in problems)


def test_blank_reviewer_is_a_problem():
    problems = validate_structure([_row(reviewer="")])
    assert any("reviewer is blank" in p for p in problems)


def test_inconsistent_catalogue_checksum_is_a_problem():
    problems = validate_structure([
        _row(row_identifier="1:IP6", catalogue_checksum="aaa"),
        _row(row_identifier="2:IP6", catalogue_checksum="bbb"),
    ])
    assert any("catalogue_checksum is not consistent" in p for p in problems)


def test_unsorted_rows_are_a_problem():
    problems = validate_structure([_row(row_identifier="2:IP6"), _row(row_identifier="1:IP6")])
    assert any("not sorted" in p for p in problems)


def test_clean_rows_pass():
    rows = [_row(row_identifier="1:IP6"), _row(row_identifier="2:IP6")]
    assert validate_structure(rows) == []


# ---- mapping integrity digest ----------------------------------------------

def test_digest_is_deterministic():
    digest1 = compute_mapping_integrity_digest(SYNTHETIC_MAPPING)
    digest2 = compute_mapping_integrity_digest(SYNTHETIC_MAPPING)
    assert digest1 == digest2


def test_digest_row_count_matches_file(tmp_path):
    p = tmp_path / "mapping.csv"
    with open(SYNTHETIC_MAPPING, encoding="utf-8") as src:
        p.write_text(src.read(), encoding="utf-8")
    digest = compute_mapping_integrity_digest(p)
    assert digest.row_count == 2


def test_digest_changes_when_file_content_changes(tmp_path):
    p = tmp_path / "mapping.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    digest1 = compute_mapping_integrity_digest(p)

    p.write_text("a,b\n1,3\n", encoding="utf-8")
    digest2 = compute_mapping_integrity_digest(p)

    assert digest1.digest != digest2.digest
