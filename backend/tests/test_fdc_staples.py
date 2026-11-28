"""Protein-free SR Legacy staples (sugar, oils, salt, ...): the committed
extract, the loader, and how the rest of the app treats a zero-protein row."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from app.canonical_foods.csv_schema import load_file
from app.catalogue_manifest import compute_fdc_catalogue_manifest
from app.database import Base
from app.fdc_staples import COLUMNS, EXTRACT_PATH, STAPLES, apply, file_sha256, load_extract
from app.ingest_fdc import build_amino_acid_profile
from app.models import Food, FoodNutrient
from app.nutrients import NUTRIENTS
from app.reference_patterns import AMINO_ACIDS
from app.search import search_foods_by_name

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
STAPLES_MIGRATION = MIGRATIONS / "5085bc12af5a_add_protein_free_sr_staples.py"
CANONICAL_MIGRATION = MIGRATIONS / "cf2908ff260e_load_canonical_foods_staples.py"


def _constant(path: Path, name: str):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not in {path.name}")


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    # one existing FDC row, so the catalogue is not empty
    session.add(Food(id=1, fdc_id=173800, data_type="sr_legacy_food", protein_g_per_100g=7.0, amino_acids={},
                     name="Chickpeas (garbanzo beans, bengal gram), mature seeds, canned, drained solids"))
    session.commit()
    yield session
    session.close()


# --- the extract -----------------------------------------------------------

def test_extract_covers_exactly_the_approved_shortlist():
    foods = load_extract()
    assert sorted(f.fdc_id for f in foods) == sorted(STAPLES)
    assert EXTRACT_PATH.read_text(encoding="utf-8").splitlines()[0] == ",".join(COLUMNS)


def test_every_staple_is_a_row_ingest_skips_and_reports_energy():
    for food in load_extract():
        assert food.data_type == "sr_legacy_food"
        assert build_amino_acid_profile({"protein": food.protein}) is None, food.name  # protein 0 / absent
        assert "energy" in food.nutrients, food.name
        assert set(food.nutrients) <= set(NUTRIENTS)


def test_migration_pins_the_extract_and_lists_the_same_ids():
    assert _constant(STAPLES_MIGRATION, "EXTRACT_SHA256") == file_sha256()
    assert sorted(_constant(STAPLES_MIGRATION, "FDC_IDS")) == sorted(STAPLES)


def test_extract_holds_no_phytate_content():
    text = EXTRACT_PATH.read_text(encoding="utf-8").lower()
    assert "phytate" not in text and "phyfoodcomp" not in text
    source = (Path(__file__).resolve().parent.parent / "app" / "fdc_staples.py").read_text(encoding="utf-8")
    assert "CompoundObservation" not in source and "compound_observations" not in source


# --- loading ---------------------------------------------------------------

def test_apply_inserts_rows_as_ingest_would_have(db):
    result = apply(db, load_extract())
    db.commit()
    assert sorted(result.inserted) == sorted(STAPLES)
    sugar = db.execute(select(Food).where(Food.fdc_id == 169655)).scalar_one()
    assert (sugar.name, sugar.data_type, sugar.protein_g_per_100g) == ("Sugars, granulated", "sr_legacy_food", 0.0)
    assert sugar.amino_acids == dict.fromkeys(AMINO_ACIDS)
    assert sugar.gtin_upc is None
    energy = db.execute(select(FoodNutrient.amount_per_100g).where(
        FoodNutrient.food_id == sugar.id, FoodNutrient.nutrient_key == "energy")).scalar_one()
    assert energy == 387.0


def test_apply_is_idempotent_and_never_touches_an_existing_row(db):
    apply(db, load_extract())
    db.commit()
    oil = db.execute(select(Food).where(Food.fdc_id == 171413)).scalar_one()
    oil.name = "edited by someone"
    db.commit()
    again = apply(db, load_extract())
    db.commit()
    assert not again.inserted and sorted(again.already_present) == sorted(STAPLES)
    assert db.get(Food, oil.id).name == "edited by someone"
    assert db.scalar(select(func.count()).select_from(Food)) == 1 + len(STAPLES)


def test_apply_is_skipped_on_an_empty_catalogue():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    assert apply(session, load_extract()).skipped_reason
    assert session.scalar(select(func.count()).select_from(Food)) == 0


def test_checksum_changes_but_existing_rows_keep_their_identity(db):
    """Expected, and why phytate stable ids need re-resolving (not re-mapping)."""
    before = compute_fdc_catalogue_manifest(db)
    apply(db, load_extract())
    db.commit()
    after = compute_fdc_catalogue_manifest(db)
    assert after.catalogue_snapshot_checksum != before.catalogue_snapshot_checksum
    assert after.catalogue_row_count == before.catalogue_row_count + len(STAPLES)
    assert db.get(Food, 1).fdc_id == 173800


# --- a zero-protein row elsewhere in the app -------------------------------

def test_recipe_with_oil_and_salt_aggregates_without_blocking_amino_acids(db):
    apply(db, load_extract())
    db.commit()
    oil = db.execute(select(Food).where(Food.fdc_id == 171413)).scalar_one()
    salt = db.execute(select(Food).where(Food.fdc_id == 173468)).scalar_one()
    chickpeas = db.get(Food, 1)
    chickpeas.amino_acids = {aa: 10.0 for aa in AMINO_ACIDS}
    items = [WeightedFood(chickpeas, 200), WeightedFood(oil, 15), WeightedFood(salt, 2)]
    rows = db.execute(select(FoodNutrient).where(FoodNutrient.food_id.in_([oil.id, salt.id]))).scalars().all()
    by_food: dict[int, list[FoodNutrient]] = {}
    for r in rows:
        by_food.setdefault(r.food_id, []).append(r)
    totals = aggregate_nutrients(items, by_food)
    assert totals["energy"] == pytest.approx(884.0 * 0.15)  # olive oil 884 kcal/100 g, salt 0
    assert totals["sodium"] > 700  # 2 g salt
    aa = aggregate_amino_acids(items)
    assert all(aa.amino_acids[k] == pytest.approx(10.0) for k in AMINO_ACIDS)  # oil/salt add no protein


def test_staples_are_found_by_name_search(db):
    apply(db, load_extract())
    db.commit()
    assert search_foods_by_name(db, "olive oil", limit=5)[0].fdc_id == 171413
    assert search_foods_by_name(db, "salt", limit=5)[0].fdc_id == 173468


# --- canonical rows anchored on staples ------------------------------------

def test_staple_canonicals_are_exactly_the_migrations_added_keys():
    canonicals = load_file(require_signoff=False)
    on_staples = {key for key, c in canonicals.items() if c.anchor_fdc_id in STAPLES}
    assert on_staples == set(_constant(CANONICAL_MIGRATION, "ADDED_KEYS"))
    names = {f.fdc_id: f.name for f in load_extract()}
    for key in on_staples:
        assert canonicals[key].anchor_fdc_name == names[canonicals[key].anchor_fdc_id], key
