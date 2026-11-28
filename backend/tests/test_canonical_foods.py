"""Canonical foods PR 4a: CSV validation (CI, no catalogue), the loader
(SQLite), the data-migration pin, and the plan 3.6 #3 invariants."""

import ast
import re
from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.canonical_foods.csv_schema import COLUMNS, CSV_PATH, CanonicalCsvError, file_sha256, load_file, parse
from app.canonical_foods.loader import load
from app.catalogue_manifest import compute_fdc_catalogue_manifest
from app.database import Base
from app.food_preparation import PREPARATION_STATES, classify_preparation
from app.models import (
    CANONICAL_PREPARATION_STATES,
    CanonicalAlias,
    CanonicalFood,
    CanonicalMember,
    CompoundObservation,
    Food,
    FoodNutrient,
)
from app.phytate_selection import select_phytate_observations
from app.reference_patterns import AMINO_ACIDS
from app.source_licence_policy import SURFACE_PERSONAL_FREE_UI

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
HEADER = ",".join(COLUMNS)
TODAY = date(2026, 11, 28)


ANCHOR_NAMES = {
    "173800": "Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids",
    "173756": "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw",
    "172420": "Lentils, raw",
    "555": "13 FOODS CHICKPEAS",
}


def _row(concept="chickpeas", state="canned_drained", alias="chickpeas", locale="*", relationship="exact",
         note="", ambiguous="", reviewer="A Reviewer", review_date="2026-11-28", anchor="173800",
         en_gb="Chickpeas, tinned, drained", key=None, anchor_name=None):
    key = key or f"{concept}.{state}"
    anchor_name = anchor_name if anchor_name is not None else ANCHOR_NAMES.get(anchor, "Some food")
    fields = [concept, key, state, en_gb, "", anchor, anchor_name, alias, locale, relationship, note, ambiguous,
              reviewer, review_date, ""]
    return ",".join(f'"{f}"' if "," in f else f for f in fields)


def _csv(*rows):
    return HEADER + "\n" + "\n".join(rows) + "\n"


# --- vocabularies ----------------------------------------------------------

def test_canonical_states_are_the_classifier_vocabulary_without_unknown():
    assert set(CANONICAL_PREPARATION_STATES) == set(PREPARATION_STATES) - {"unknown"}


def test_schema_migration_check_lists_match_the_models():
    text = (MIGRATIONS / "bddd919dd8dd_add_canonical_food_tables.py").read_text(encoding="utf-8")
    listed = set(re.findall(r"'([a-z_]+)'", text.split("_PREPARATION_STATES = (", 1)[1].split(")", 1)[0]))
    assert listed == set(CANONICAL_PREPARATION_STATES)


# --- CSV validation (pure) -------------------------------------------------

def test_valid_minimal_file_parses():
    canonicals = parse(_csv(_row(), _row(alias="tinned chickpeas", locale="en-GB")), today=TODAY)
    (c,) = canonicals.values()
    assert c.key == "chickpeas.canned_drained" and c.anchor_fdc_id == 173800
    assert [a.alias for a in c.aliases] == ["chickpeas", "tinned chickpeas"]


@pytest.mark.parametrize("row, message", [
    (_row(state="unknown"), "preparation_state"),
    (_row(state="boiled"), "preparation_state"),
    (_row(key="chickpeas.tinned"), "canonical_key"),
    (_row(concept="Chick Peas"), "lowercase slug"),
    (_row(anchor="abc"), "anchor_fdc_id"),
    (_row(alias="Chickpeas"), "lowercase"),
    (_row(locale="en-AU"), "alias_locale"),
    (_row(relationship="synonym"), "relationship"),
    (_row(relationship="close_analogue"), "alias_note"),
    (_row(ambiguous="maybe"), "ambiguous"),
    (_row(reviewer=""), "not been signed off"),
    (_row(reviewer="PENDING"), "not been signed off"),
    (_row(review_date="28/11/2026"), "ISO date"),
    (_row(review_date="2026-11-28T00:00"), "ISO date"),
    (_row(review_date="20261128"), "ISO date"),
    (_row(anchor_name=""), "anchor_fdc_name"),
    (_row(review_date="2027-01-01"), "future"),
    (_row(en_gb=""), "display_name_en_gb"),
])
def test_invalid_rows_are_rejected(row, message):
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(row), today=TODAY)
    assert any(message in p for p in e.value.problems), e.value.problems


def test_every_problem_is_reported_at_once():
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(_row(reviewer=""), _row(alias="x", locale="xx")), today=TODAY)
    assert len(e.value.problems) >= 2


def test_spreadsheet_damage_is_rejected_with_a_hint():
    garbled = _row(en_gb="Tomato pur\u00c3\u00a9e (paste)")
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(garbled), today=TODAY)
    assert any("garbled characters" in p and "spreadsheet" in p for p in e.value.problems)
    with pytest.raises(CanonicalCsvError, match="byte-order mark"):
        parse("\ufeff" + _csv(_row()), today=TODAY)
    parse(_csv(_row(en_gb="Tomato pur\u00e9e (paste)")), today=TODAY)  # real UTF-8 is fine


def test_the_file_is_read_as_utf8_whatever_the_platform_default(tmp_path):
    path = tmp_path / "c.csv"
    path.write_bytes(_csv(_row(en_gb="Tomato pur\u00e9e (paste)")).encode("utf-8"))
    (c,) = load_file(path).values()
    assert c.display_name_en_gb == "Tomato pur\u00e9e (paste)"


def test_header_must_match():
    with pytest.raises(CanonicalCsvError):
        parse("concept,alias\nx,y\n", today=TODAY)


def test_unquoted_comma_is_reported_not_crashed():
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(_row() + ",extra"), today=TODAY)
    assert "wrong number of fields" in e.value.problems[0]


def test_canonical_columns_must_agree_across_alias_rows():
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(_row(), _row(alias="tinned chickpeas", anchor="999")), today=TODAY)
    assert any("differ" in p for p in e.value.problems)


def test_one_alias_may_cover_variants_of_one_concept():
    parse(_csv(_row(), _row(state="dry", anchor="173756")), today=TODAY)


def test_one_alias_for_two_concepts_needs_ambiguous_on_every_row():
    a = _row(concept="biscuits_uk", state="unspecified", alias="biscuit", anchor="1")
    b = _row(concept="biscuits_us", state="unspecified", alias="biscuit", anchor="2")
    with pytest.raises(CanonicalCsvError):
        parse(_csv(a, b), today=TODAY)
    parse(_csv(
        _row(concept="biscuits_uk", state="unspecified", alias="biscuit", anchor="1", ambiguous="yes"),
        _row(concept="biscuits_us", state="unspecified", alias="biscuit", anchor="2", ambiguous="yes"),
    ), today=TODAY)


def test_alias_may_not_be_another_concepts_name():
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(_row(), _row(concept="lentils", state="dry", alias="chickpeas", anchor="172420")), today=TODAY)
    assert any("another concept" in p or "points at concepts" in p for p in e.value.problems)


def test_one_anchor_may_not_anchor_two_canonicals():
    with pytest.raises(CanonicalCsvError) as e:
        parse(_csv(_row(), _row(state="dry")), today=TODAY)
    assert any("more than one canonical" in p for p in e.value.problems)


# --- the real file and its data migration ------------------------------------

def test_reviewed_file_is_valid_and_fully_signed_off():
    """Fails while any row still says reviewer=PENDING: sign-off is part of
    the review (owner's decision for PR 4)."""
    canonicals = load_file()
    assert canonicals


def test_file_holds_no_phytate_review_content():
    text = CSV_PATH.read_text(encoding="utf-8").lower()
    for marker in ("phyfoodcomp", "phytate", "compound_observation", "source_food_description"):
        assert marker not in text


def _data_migrations():
    """(revision, down_revision, CSV_SHA256) for every migration that pins the CSV."""
    found = []
    for path in MIGRATIONS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values = {}
        for node in tree.body:
            target = node.target if isinstance(node, ast.AnnAssign) else (
                node.targets[0] if isinstance(node, ast.Assign) else None)
            if isinstance(target, ast.Name) and isinstance(getattr(node, "value", None), ast.Constant):
                values[target.id] = node.value.value
        if "CSV_SHA256" in values:
            found.append((values["revision"], values.get("down_revision"), values["CSV_SHA256"]))
    return found


def test_newest_data_migration_pins_the_current_file():
    """Every reviewed CSV edit needs a new data migration carrying the new
    checksum; otherwise production would never load it."""
    migrations = {r: sha for r, _, sha in _data_migrations()}
    assert migrations
    # the real revision order: other migrations (e.g. the FDC staples) may
    # sit between two canonical data migrations
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS.parent))
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1, "migrations must form one chain"
    ordered = [rev.revision for rev in script.walk_revisions()]  # newest first
    newest = next(r for r in ordered if r in migrations)
    assert migrations[newest] == file_sha256(), (
        f"add a data migration with CSV_SHA256 = {file_sha256()!r} (or update the unreleased one)"
    )


# --- loader (SQLite) -------------------------------------------------------

ANCHORS = [
    (173800, "sr_legacy_food", "Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids"),
    (173756, "sr_legacy_food", "Chickpeas (garbanzo beans, bengal gram), mature seeds, raw"),
    (172420, "sr_legacy_food", "Lentils, raw"),
    (555, "branded_food", "13 FOODS CHICKPEAS"),
]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    for i, (fdc_id, data_type, name) in enumerate(ANCHORS, start=1):
        session.add(Food(id=i, fdc_id=fdc_id, data_type=data_type, name=name, protein_g_per_100g=7.0,
                         amino_acids=dict.fromkeys(AMINO_ACIDS)))
        session.add(FoodNutrient(food_id=i, nutrient_key="energy", amount_per_100g=100.0))
    session.commit()
    yield session
    session.close()


def _two_canonicals():
    return parse(_csv(
        _row(), _row(alias="tinned chickpeas", locale="en-GB"),
        _row(concept="lentils", state="dry", alias="lentils", anchor="172420", en_gb="Lentils, dried"),
    ), today=TODAY)


def test_load_creates_rows_and_is_idempotent(db):
    result = load(db, _two_canonicals())
    db.commit()
    assert sorted(result.created) == ["chickpeas.canned_drained", "lentils.dry"]
    food = db.execute(select(CanonicalFood).where(CanonicalFood.key == "chickpeas.canned_drained")).scalar_one()
    assert food.default_food_id == 1 and food.status == "active"
    assert food.review_ref == "canonical_foods_en_gb.csv#chickpeas.canned_drained"
    assert db.scalar(select(func.count()).select_from(CanonicalAlias)) == 3
    members = db.execute(select(CanonicalMember)).scalars().all()
    assert {(m.food_id, m.role, m.match_method, m.confidence) for m in members} == {
        (1, "anchor", "reviewed", "high"), (3, "anchor", "reviewed", "high"),
    }

    again = load(db, _two_canonicals())
    db.commit()
    assert sorted(again.unchanged) == ["chickpeas.canned_drained", "lentils.dry"]
    assert not again.created and not again.updated
    assert db.scalar(select(func.count()).select_from(CanonicalAlias)) == 3


def test_correction_replaces_by_key_and_removal_retires(db):
    load(db, _two_canonicals())
    db.commit()
    corrected = parse(_csv(_row(alias="chickpeas, tinned".replace(",", "") )), today=TODAY)
    result = load(db, corrected)
    db.commit()
    assert result.updated == ["chickpeas.canned_drained"]
    assert result.retired == ["lentils.dry"]
    lentils = db.execute(select(CanonicalFood).where(CanonicalFood.key == "lentils.dry")).scalar_one()
    assert lentils.status == "retired"
    assert db.execute(select(CanonicalAlias.alias)).scalars().all() == ["chickpeas tinned"]


@pytest.mark.parametrize("row, message", [
    (_row(anchor="999999"), "not in the catalogue"),
    (_row(anchor="555"), "not Foundation or SR Legacy"),
    (_row(state="dry"), "classified 'canned_drained', not 'dry'"),
    (_row(anchor_name="Chickpeas, dry"), "but the file says 'Chickpeas, dry'"),
])
def test_bad_anchor_fails_the_whole_load(db, row, message):
    canonicals = parse(_csv(row, _row(concept="lentils", state="dry", alias="lentils", anchor="172420")), today=TODAY)
    with pytest.raises(CanonicalCsvError) as e:
        load(db, canonicals)
    db.rollback()
    assert any(message in p for p in e.value.problems), e.value.problems
    assert db.scalar(select(func.count()).select_from(CanonicalFood)) == 0


def test_anchor_without_energy_fails_the_load(db):
    db.query(FoodNutrient).filter(FoodNutrient.food_id == 1).delete()
    db.commit()
    with pytest.raises(CanonicalCsvError) as e:
        load(db, _two_canonicals())
    db.rollback()
    assert e.value.problems == ["chickpeas.canned_drained: anchor "
                                "'Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids' "
                                "reports no energy value"]


def test_empty_catalogue_is_skipped_not_failed():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    result = load(session, _two_canonicals())
    assert result.skipped_reason
    assert session.scalar(select(func.count()).select_from(CanonicalFood)) == 0


def test_every_anchor_has_its_canonicals_state(db):
    """Plan 3.1 invariant, checked after a load."""
    load(db, _two_canonicals())
    db.commit()
    rows = db.execute(
        select(CanonicalFood.preparation_state, Food.name, Food.data_type)
        .join(CanonicalMember, CanonicalMember.canonical_food_id == CanonicalFood.id)
        .join(Food, Food.id == CanonicalMember.food_id)
        .where(CanonicalMember.role.in_(("anchor", "member")))
    ).all()
    assert rows
    for state, name, data_type in rows:
        assert classify_preparation(name, data_type) == state


def test_load_leaves_the_catalogue_checksum_unchanged(db):
    before = compute_fdc_catalogue_manifest(db).catalogue_snapshot_checksum
    load(db, _two_canonicals())
    db.commit()
    assert compute_fdc_catalogue_manifest(db).catalogue_snapshot_checksum == before


def test_phytate_selection_identical_before_and_after_load(db):
    """Canonical tables are never consulted for phytate (plan 1.5 #2). The
    observation here is a synthetic test value, not source data."""
    db.add(CompoundObservation(
        compound="phytate", original_value=100.0, original_unit="mg", original_basis="per_100g_edible_portion",
        original_value_text="100.0", value_qualifier="measured", original_value_provenance="source_reported",
        source_food_description="Test food", source_dataset_name="PhyFoodComp1.0", source_dataset_citation="c",
        source_dataset_version="1.0", source_access_date=date(2026, 8, 21), match_relationship="close_analogue",
        match_confidence=0.8, matched_food_id=1,
    ))
    db.commit()
    before = select_phytate_observations(db, 1, SURFACE_PERSONAL_FREE_UI)
    load(db, _two_canonicals())
    db.commit()
    after = select_phytate_observations(db, 1, SURFACE_PERSONAL_FREE_UI)
    assert repr(before) == repr(after)


def test_canonical_modules_never_touch_compound_data():
    package = Path(__file__).resolve().parent.parent / "app" / "canonical_foods"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "CompoundObservation" not in text and "compound_observations" not in text, path.name
