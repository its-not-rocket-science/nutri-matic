"""Foundation Foods energy/folate fallbacks (canonical foods plan 1.3)."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.catalogue_manifest import compute_fdc_catalogue_manifest
from app.database import Base
from app.foundation_nutrients import (
    COLUMNS,
    EXTRACT_PATH,
    FALLBACK_NBR_TO_FIELD,
    FOLATE_TOTAL_EXCLUDED,
    Backfill,
    apply,
    apply_fallbacks,
    file_sha256,
    load_extract,
)
from app.ingest_fdc import NUTRIENT_NBR_TO_FIELD
from app.models import Food, FoodNutrient
from app.nutrients import NUTRIENTS

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "868a02252a15_backfill_foundation_energy_folate.py"


# --- the rules -------------------------------------------------------------

@pytest.mark.parametrize("given, expected_energy, source", [
    ({"energy": 229.0, "energy_atwater_specific": 230.0, "energy_atwater_general": 243.0}, 229.0, None),
    ({"energy_atwater_specific": 229.0, "energy_atwater_general": 243.0}, 229.0, "958"),
    ({"energy_atwater_general": 243.0}, 243.0, "957"),
    ({}, None, None),
])
def test_energy_prefers_208_then_specific_then_general(given, expected_energy, source):
    nutrients = dict(given)
    filled = apply_fallbacks(1, "foundation_food", nutrients)
    assert nutrients.get("energy") == expected_energy
    assert filled.get("energy") == source


def test_folate_total_fills_foundation_dfe_only_when_absent_and_not_fortified():
    n = {"folate_total": 40.0}
    assert apply_fallbacks(1, "foundation_food", n) == {"folate": "417"} and n["folate"] == 40.0
    n = {"folate_total": 40.0, "folate": 55.0}  # a real DFE wins
    assert apply_fallbacks(1, "foundation_food", n) == {} and n["folate"] == 55.0
    n = {"folate_total": 40.0}  # SR Legacy reports DFE itself; never fill it from total
    assert apply_fallbacks(1, "sr_legacy_food", n) == {} and "folate" not in n
    fortified = next(iter(FOLATE_TOTAL_EXCLUDED))
    n = {"folate_total": 160.0}
    assert apply_fallbacks(fortified, "foundation_food", n) == {} and "folate" not in n


def test_fallback_fields_are_read_but_never_stored():
    for nbr, field in FALLBACK_NBR_TO_FIELD.items():
        assert NUTRIENT_NBR_TO_FIELD[nbr] == field
        assert field not in NUTRIENTS
    assert NUTRIENT_NBR_TO_FIELD["208"] == "energy" and NUTRIENT_NBR_TO_FIELD["435"] == "folate"


def test_exclusions_are_the_reviewed_fortified_rows():
    assert len(FOLATE_TOTAL_EXCLUDED) == 7
    assert all(("enriched" in n.lower() or "semolina" in n.lower() or "breaded" in n.lower())
               for n in FOLATE_TOTAL_EXCLUDED.values())


# --- the extract -----------------------------------------------------------

def test_extract_follows_the_rules():
    rows = load_extract()
    assert EXTRACT_PATH.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLUMNS)
    assert {(r.nutrient_key, r.source_nbr) for r in rows} == {("energy", "958"), ("energy", "957"), ("folate", "417")}
    assert not [r for r in rows if r.nutrient_key == "folate" and r.fdc_id in FOLATE_TOTAL_EXCLUDED]
    assert len({(r.fdc_id, r.nutrient_key) for r in rows}) == len(rows)
    assert sum(r.nutrient_key == "energy" for r in rows) == 241  # 132 -> 373 of 420 rows with energy
    assert sum(r.nutrient_key == "folate" for r in rows) == 149  # 156 with total folate, minus 7 fortified


def test_migration_pins_the_extract():
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    pin = next(ast.literal_eval(n.value) for n in tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "EXTRACT_SHA256")
    assert pin == file_sha256()


def test_extract_holds_no_phytate_content():
    assert "phytate" not in EXTRACT_PATH.read_text(encoding="utf-8").lower()


# --- loading ---------------------------------------------------------------

ROWS = [
    Backfill(321358, "Hummus, commercial", "energy", 229.0, "958"),
    Backfill(321358, "Hummus, commercial", "folate", 83.0, "417"),
    Backfill(2685577, "Eggplant, raw", "energy", 25.0, "957"),
    Backfill(999999, "Not here", "energy", 1.0, "958"),
]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        Food(id=1, fdc_id=321358, data_type="foundation_food", name="Hummus, commercial", protein_g_per_100g=7.0,
             amino_acids={}),
        Food(id=2, fdc_id=2685577, data_type="foundation_food", name="Eggplant, raw, renamed", protein_g_per_100g=1.0,
             amino_acids={}),
    ])
    session.add(FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=230.0))  # already reported
    session.commit()
    yield session
    session.close()


def test_apply_adds_only_missing_values_for_the_same_food(db):
    result = apply(db, ROWS)
    db.commit()
    assert (result.inserted, result.already_present, result.food_missing) == (1, 1, 1)
    assert len(result.name_mismatch) == 1 and "2685577" in result.name_mismatch[0]
    values = dict(list(db.execute(select(FoodNutrient.nutrient_key, FoodNutrient.amount_per_100g)
                                  .where(FoodNutrient.food_id == 1)).tuples()))
    assert values == {"energy": 230.0, "folate": 83.0}  # existing energy untouched
    assert not db.execute(select(FoodNutrient).where(FoodNutrient.food_id == 2)).first()


def test_apply_is_idempotent_and_leaves_the_checksum(db):
    before = compute_fdc_catalogue_manifest(db).catalogue_snapshot_checksum
    apply(db, ROWS)
    db.commit()
    again = apply(db, ROWS)
    db.commit()
    assert again.inserted == 0 and again.already_present == 2
    assert db.scalar(select(func.count()).select_from(FoodNutrient)) == 2
    assert compute_fdc_catalogue_manifest(db).catalogue_snapshot_checksum == before


def test_apply_is_skipped_on_an_empty_catalogue():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    assert apply(sessionmaker(bind=engine)(), ROWS).skipped_reason


# --- ingest ----------------------------------------------------------------

def test_ingest_applies_the_fallbacks(monkeypatch, tmp_path):
    from app import ingest_fdc

    d = tmp_path / "foundation"
    d.mkdir()
    (d / "food.csv").write_text(
        "fdc_id,data_type,description\n"
        "321358,foundation_food,\"Hummus, commercial\"\n"
        "789890,foundation_food,\"Flour, wheat, all-purpose, enriched, bleached\"\n", encoding="utf-8")
    (d / "nutrient.csv").write_text("id,nutrient_nbr\n1003,203\n2047,957\n2048,958\n1177,417\n", encoding="utf-8")
    (d / "food_nutrient.csv").write_text(
        "fdc_id,nutrient_id,amount\n"
        "321358,1003,7.35\n321358,2047,243\n321358,2048,229\n321358,1177,83\n"
        "789890,1003,10.9\n789890,2047,366\n789890,1177,160\n", encoding="utf-8")
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr(ingest_fdc, "engine", engine)
    monkeypatch.setattr(ingest_fdc, "SessionLocal", Session)
    ingest_fdc.main(["--dir", str(d), "--no-staples"])

    session = Session()
    got = {(fdc, key): amount for fdc, key, amount in session.execute(
        select(Food.fdc_id, FoodNutrient.nutrient_key, FoodNutrient.amount_per_100g)
        .join(Food, Food.id == FoodNutrient.food_id)).tuples()}
    assert got[(321358, "energy")] == 229.0  # specific factors (958) over general (957)
    assert got[(321358, "folate")] == 83.0
    assert got[(789890, "energy")] == 366.0  # general factors when that's all there is
    assert (789890, "folate") not in got  # enriched: total folate would understate DFE
    session.close()
