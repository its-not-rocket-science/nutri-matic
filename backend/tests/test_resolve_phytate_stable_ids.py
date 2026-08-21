"""Tests for app.resolve_phytate_stable_ids and app.catalogue_manifest
(prompts.txt PROMPT 2 of the phytate/mineral-bioavailability extension).
Uses an in-memory SQLite Food fixture, same convention as
test_compound_observations_schema.py -- nothing here depends on a
Postgres-only feature, and this module never invokes any part of
app.stock_recipes.food_matching (the fuzzy/alias matcher), which is the
point being tested."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalogue_manifest import (
    IMPORTER_VERSION,
    UNRECORDED_RELEASE,
    ManifestSnapshot,
    compute_fdc_catalogue_manifest,
)
from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS
from app.resolve_phytate_stable_ids import (
    CatalogueDriftError,
    check_catalogue_manifest,
    resolve_mapping_rows,
)


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


def _mapping_row(**overrides):
    row = dict(
        row_identifier="X:1", food_description="Test food", compound_fraction="IP6", value="100.0",
        approved_fdc_food="Rice, white", candidate_data_type="sr_legacy_food", match_scope="category_estimate",
        review_verdict="approve", reviewer="Paul S", review_date="16/08/2026", review_notes="",
    )
    row.update(overrides)
    return row


# ---- resolve_mapping_rows ------------------------------------------------

def test_unique_match_resolves_with_food_id_and_fdc_id(session):
    food = _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=12345)
    session.add(food)
    session.commit()

    resolved, exceptions = resolve_mapping_rows(session, [_mapping_row()], overrides={}, catalogue_checksum="abc")

    assert exceptions == []
    assert len(resolved) == 1
    assert resolved[0].food_id == food.id
    assert resolved[0].fdc_id == 12345
    assert resolved[0].catalogue_checksum == "abc"


def test_missing_target_is_a_blocking_exception(session):
    resolved, exceptions = resolve_mapping_rows(session, [_mapping_row()], overrides={}, catalogue_checksum="abc")

    assert resolved == []
    assert len(exceptions) == 1
    assert exceptions[0].reason == "missing"


def test_duplicate_name_and_data_type_is_not_auto_resolved(session):
    session.add_all([
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111),
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=222),
    ])
    session.commit()

    resolved, exceptions = resolve_mapping_rows(session, [_mapping_row()], overrides={}, catalogue_checksum="abc")

    assert resolved == []
    assert len(exceptions) == 1
    assert exceptions[0].reason == "duplicate"
    assert "111" in exceptions[0].detail and "222" in exceptions[0].detail


def test_duplicate_resolved_by_valid_override(session):
    session.add_all([
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111),
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=222),
    ])
    session.commit()

    resolved, exceptions = resolve_mapping_rows(
        session, [_mapping_row()], overrides={"X:1": "222"}, catalogue_checksum="abc",
    )

    assert exceptions == []
    assert len(resolved) == 1
    assert resolved[0].fdc_id == 222


def test_override_naming_an_fdc_id_not_among_candidates_is_a_blocking_exception(session):
    """Required by prompts.txt PROMPT 2 rule 3: never choose query order,
    minimum Food.id, or the first row returned -- an override must
    actually correspond to a real candidate, not be accepted blindly."""
    session.add_all([
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111),
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=222),
    ])
    session.commit()

    resolved, exceptions = resolve_mapping_rows(
        session, [_mapping_row()], overrides={"X:1": "999"}, catalogue_checksum="abc",
    )

    assert resolved == []
    assert len(exceptions) == 1
    assert exceptions[0].reason == "override_mismatch"


def test_matched_food_with_no_fdc_id_is_a_stale_exception(session):
    session.add(_food(name="Rice, white", data_type="sr_legacy_food", fdc_id=None))
    session.commit()

    resolved, exceptions = resolve_mapping_rows(session, [_mapping_row()], overrides={}, catalogue_checksum="abc")

    assert resolved == []
    assert len(exceptions) == 1
    assert exceptions[0].reason == "stale_no_fdc_id"


def test_case_difference_never_fuzzily_resolves(session):
    """No fuzzy matching, per prompts.txt PROMPT 2 rule 4 -- a
    near-identical but not byte-identical name must be 'missing', never
    resolved via similarity."""
    session.add(_food(name="Rice, White", data_type="sr_legacy_food", fdc_id=111))  # capital W
    session.commit()

    resolved, exceptions = resolve_mapping_rows(
        session, [_mapping_row(approved_fdc_food="Rice, white")], overrides={}, catalogue_checksum="abc",
    )

    assert resolved == []
    assert exceptions[0].reason == "missing"


def test_every_row_is_resolved_or_blocked(session):
    session.add(_food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111))
    session.commit()

    rows = [
        _mapping_row(row_identifier="A:1", approved_fdc_food="Rice, white"),
        _mapping_row(row_identifier="B:1", approved_fdc_food="Nonexistent food"),
    ]
    resolved, exceptions = resolve_mapping_rows(session, rows, overrides={}, catalogue_checksum="abc")

    assert len(resolved) + len(exceptions) == len(rows)


def test_resolution_is_deterministic_across_runs(session):
    session.add_all([
        _food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111),
        _food(name="Oats", data_type="foundation_food", fdc_id=222),
    ])
    session.commit()

    rows = [
        _mapping_row(row_identifier="B:1", approved_fdc_food="Oats", candidate_data_type="foundation_food"),
        _mapping_row(row_identifier="A:1", approved_fdc_food="Rice, white"),
    ]

    run1 = resolve_mapping_rows(session, rows, overrides={}, catalogue_checksum="abc")
    run2 = resolve_mapping_rows(session, rows, overrides={}, catalogue_checksum="abc")

    assert run1 == run2


def test_no_database_writes_occur(session):
    session.add(_food(name="Rice, white", data_type="sr_legacy_food", fdc_id=111))
    session.commit()
    count_before = session.query(Food).count()

    resolve_mapping_rows(session, [_mapping_row()], overrides={}, catalogue_checksum="abc")
    session.rollback()  # would undo any uncommitted write; state must be identical regardless

    assert session.query(Food).count() == count_before


# ---- catalogue manifest ---------------------------------------------------

def test_compute_manifest_excludes_foods_without_fdc_id(session):
    session.add_all([
        _food(name="Has fdc", fdc_id=111),
        _food(name="Manual food", fdc_id=None),
    ])
    session.commit()

    snapshot = compute_fdc_catalogue_manifest(session, as_of=date(2026, 8, 21))

    assert snapshot.row_count == 1
    assert snapshot.release_version == UNRECORDED_RELEASE
    assert snapshot.importer_version == IMPORTER_VERSION


def test_compute_manifest_is_deterministic(session):
    session.add_all([_food(name="A", fdc_id=1), _food(name="B", fdc_id=2)])
    session.commit()

    snap1 = compute_fdc_catalogue_manifest(session, as_of=date(2026, 8, 21))
    snap2 = compute_fdc_catalogue_manifest(session, as_of=date(2026, 8, 21))

    assert snap1.checksum == snap2.checksum


def test_compute_manifest_changes_when_food_table_changes(session):
    session.add(_food(name="A", fdc_id=1))
    session.commit()
    before = compute_fdc_catalogue_manifest(session)

    session.add(_food(name="B", fdc_id=2))
    session.commit()
    after = compute_fdc_catalogue_manifest(session)

    assert before.checksum != after.checksum


def _snapshot(**overrides):
    defaults = dict(
        source_name="usda_fdc_food_catalogue", release_version=UNRECORDED_RELEASE,
        import_date=date(2026, 8, 21), checksum="abc", row_count=1, importer_version=IMPORTER_VERSION,
    )
    defaults.update(overrides)
    return ManifestSnapshot(**defaults)


def test_missing_expected_manifest_is_not_an_error():
    check_catalogue_manifest(expected=None, actual=_snapshot())  # must not raise


def test_matching_manifest_passes():
    check_catalogue_manifest(expected=_snapshot(), actual=_snapshot())  # must not raise


def test_checksum_mismatch_raises_catalogue_drift_error():
    with pytest.raises(CatalogueDriftError):
        check_catalogue_manifest(expected=_snapshot(checksum="old"), actual=_snapshot(checksum="new"))


def test_importer_version_mismatch_raises_catalogue_drift_error():
    with pytest.raises(CatalogueDriftError):
        check_catalogue_manifest(
            expected=_snapshot(importer_version="fdc-catalogue-manifest-v0"), actual=_snapshot(),
        )
