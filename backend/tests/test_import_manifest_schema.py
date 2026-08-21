"""Schema-only tests for ImportManifest (prompts.txt PROMPT 2 of the
phytate/mineral-bioavailability extension) -- constraints and
nullability, same in-memory-SQLite convention as
test_compound_observations_schema.py."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ImportManifest


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    yield db
    db.close()


def _minimal_kwargs(**overrides):
    kwargs = dict(
        source_name="usda_fdc_food_catalogue",
        release_version="unrecorded_at_ingestion",
        import_date=date(2026, 8, 21),
        checksum="abc123",
        row_count=1400000,
        importer_version="fdc-catalogue-manifest-v1",
    )
    kwargs.update(overrides)
    return kwargs


def test_minimal_manifest_persists(session):
    manifest = ImportManifest(**_minimal_kwargs())
    session.add(manifest)
    session.commit()

    saved = session.query(ImportManifest).one()
    assert saved.notes is None
    assert isinstance(saved.created_at, datetime)


@pytest.mark.parametrize("required_field", [
    "source_name", "release_version", "import_date", "checksum", "row_count", "importer_version",
])
def test_required_field_cannot_be_null(session, required_field):
    kwargs = _minimal_kwargs(**{required_field: None})
    session.add(ImportManifest(**kwargs))
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_same_source_and_checksum_cannot_be_recorded_twice(session):
    session.add(ImportManifest(**_minimal_kwargs()))
    session.commit()

    session.add(ImportManifest(**_minimal_kwargs()))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_same_source_with_different_checksum_is_allowed(session):
    """Multiple snapshots of the same source over time are expected --
    the unique constraint only guards against recording an identical
    snapshot twice, not against re-snapshotting after real drift."""
    session.add(ImportManifest(**_minimal_kwargs()))
    session.commit()

    session.add(ImportManifest(**_minimal_kwargs(checksum="def456")))
    session.commit()

    assert session.query(ImportManifest).count() == 2
