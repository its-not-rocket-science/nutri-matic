"""Tests for app.validate_stable_id_mapping (prompts.txt PROMPT 12) --
offline structural validation of the stable-ID mapping artifact, and the
mapping-integrity digest. Uses only synthetic fixtures/fabricated rows;
never reads the real private mapping file, matching PROMPT 12's own
requirement that ordinary public CI needs neither the real FDC catalogue
nor real PhyFoodComp artifacts."""

import csv
import json
import re
from pathlib import Path

from app.resolve_phytate_stable_ids import MAPPING_OUT_COLUMNS
from app.validate_stable_id_mapping import (
    DEFAULT_DIGEST_FILE,
    SCHEMA_VERSION,
    compute_mapping_integrity_digest,
    validate_structure,
    verify_against_live_catalogue,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_MAPPING = FIXTURES_DIR / "synthetic_stable_id_mapping.csv"

SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


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


# ---- verify_against_live_catalogue -----------------------------------------

class _FakeFood:
    def __init__(self, id, fdc_id):
        self.id = id
        self.fdc_id = fdc_id


class _FakeDb:
    """Minimal stand-in for a Session -- only .get(Food, id) is used."""

    def __init__(self, foods_by_id):
        self._foods_by_id = foods_by_id

    def get(self, _model, food_id):
        return self._foods_by_id.get(food_id)


def test_verify_against_live_catalogue_matching_pair_is_clean():
    db = _FakeDb({1: _FakeFood(id=1, fdc_id=100001)})
    rows = [_row(row_identifier="1:IP6", food_id="1", fdc_id="100001")]
    assert verify_against_live_catalogue(db, rows) == []


def test_verify_against_live_catalogue_catches_altered_fdc_id():
    """The exact gap a bot-review finding on PR #60 caught: an operator
    hand-altering fdc_id in the mapping (and updating the digest to
    match) must still be caught here, since the digest alone can't."""
    db = _FakeDb({1: _FakeFood(id=1, fdc_id=100001)})
    rows = [_row(row_identifier="1:IP6", food_id="1", fdc_id="999999")]
    problems = verify_against_live_catalogue(db, rows)
    assert len(problems) == 1
    assert "mismatch" in problems[0]


def test_verify_against_live_catalogue_catches_missing_food_id():
    db = _FakeDb({})
    rows = [_row(row_identifier="1:IP6", food_id="404", fdc_id="100001")]
    problems = verify_against_live_catalogue(db, rows)
    assert len(problems) == 1
    assert "does not exist" in problems[0]


def test_verify_against_live_catalogue_reports_every_mismatch_not_just_first():
    db = _FakeDb({1: _FakeFood(id=1, fdc_id=1), 2: _FakeFood(id=2, fdc_id=2)})
    rows = [
        _row(row_identifier="1:IP6", food_id="1", fdc_id="999"),
        _row(row_identifier="2:IP6", food_id="2", fdc_id="888"),
    ]
    assert len(verify_against_live_catalogue(db, rows)) == 2


# ---- the committed public digest metadata file ------------------------------

def test_committed_digest_file_has_valid_shape():
    """Requirement: public CI must notice if docs/phytate-review/
    stable_id_mapping_digest.json -- the public aggregate metadata meant
    to detect private-artifact drift -- is ever hand-edited to something
    arbitrary (wrong schema version, negative row count, malformed hash).
    A bot-review finding on PR #60 caught that nothing previously read
    this file at all in public CI."""
    assert DEFAULT_DIGEST_FILE.is_file(), f"{DEFAULT_DIGEST_FILE} must be committed"
    data = json.loads(DEFAULT_DIGEST_FILE.read_text(encoding="utf-8"))

    assert data["schema_version"] == SCHEMA_VERSION
    assert isinstance(data["row_count"], int) and data["row_count"] > 0
    assert SHA256_HEX_RE.match(data["digest"]), f"digest {data['digest']!r} is not a 64-char hex SHA-256"
