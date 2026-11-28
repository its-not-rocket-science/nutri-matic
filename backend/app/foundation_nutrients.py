"""Energy and folate for USDA Foundation Foods rows (canonical foods plan 1.3).

ingest_fdc.py maps energy from FDC nutrient 208 and folate from 435
(Folate, DFE), the numbers SR Legacy uses. Foundation Foods mostly
publishes different ones, so on the 420 Foundation rows the app ingests
only 132 had energy and none had folate (Foundation 2026-04-30 export).
These fallbacks, applied only where the primary number is absent:

  * energy: 208, else 958 (Energy, Atwater Specific Factors), else 957
    (Energy, Atwater General Factors). Where Foundation reports both 208
    and 958 they agree (e.g. "Hummus, commercial": 229 and 229), so 958 is
    the same quantity under another number; 957 is the general-factor
    estimate, used only when neither is reported.
  * folate (DFE): Foundation never reports 435, 432 (food folate) or 431
    (folic acid), only 417 (Folate, total). For a food without added folic
    acid, total folate equals DFE, so 417 is used for Foundation rows.
    For a fortified food, total folate understates DFE (folic acid counts
    1.7 times), so the owner-reviewed rows in FOLATE_TOTAL_EXCLUDED keep
    folate "not reported" instead of an understated value.

ingest_fdc.py applies these on every ingest. Databases ingested before
that get the values from the committed extract
(foundation_nutrients_2026_04_30.csv) through an Alembic data migration,
which only adds a missing nutrient row and never changes an existing one.

    python -m app.foundation_nutrients build  --foundation-dir <unzipped export>
    python -m app.foundation_nutrients verify --foundation-dir <unzipped export>
    python -m app.foundation_nutrients load [--dry-run]

Nutrient rows are outside the catalogue snapshot checksum
(catalogue_manifest.py hashes foods' id, fdc_id, name and data_type only),
so phytate stable ids are unaffected. Diary days that are not snapshotted
are computed live, so their totals pick up the added energy and folate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Food, FoodNutrient

EXTRACT_PATH = Path(__file__).resolve().parent / "foundation_nutrients_2026_04_30.csv"
FOUNDATION_ZIP = "FoodData_Central_foundation_food_csv_2026-04-30.zip"
FOUNDATION_ZIP_SHA256 = "d6d4f41dcd19a46abcdd67775379cb6f0292ff08daa7e0680fdd0982830bf57b"
COLUMNS = ("fdc_id", "name", "nutrient_key", "amount_per_100g", "source_nutrient_nbr")

# Extra FDC nutrient numbers ingest_fdc.py reads into these field names.
# They are not NUTRIENTS keys, so they are never stored themselves.
FALLBACK_NBR_TO_FIELD = {
    "957": "energy_atwater_general",
    "958": "energy_atwater_specific",
    "417": "folate_total",
}

# Owner-reviewed (PR review, 2026-11-28): Foundation rows whose name says
# they are enriched with folic acid, or that are typically made from
# enriched flour, so total folate would understate DFE.
FOLATE_TOTAL_EXCLUDED: dict[int, str] = {
    324317: "Onion rings, breaded, par fried, frozen, prepared, heated in oven",
    789890: "Flour, wheat, all-purpose, enriched, bleached",
    789951: "Flour, wheat, all-purpose, enriched, unbleached",
    790146: "Flour, bread, white, enriched, unbleached",
    790276: "Flour, corn, yellow, fine meal, enriched",
    2003588: "Flour, semolina, coarse and semi-coarse",
    2003589: "Flour, semolina, fine",
}


def apply_fallbacks(fdc_id: int, data_type: str | None, nutrients: dict[str, float]) -> dict[str, str]:
    """Fill energy and folate in `nutrients` (field -> amount, as
    ingest_fdc.load_nutrient_amounts returns it) from the fallback numbers,
    only where the primary value is absent. Returns {nutrient_key: source
    nutrient number} for each value it filled."""
    filled = {}
    if "energy" not in nutrients:
        for source, nbr in (("energy_atwater_specific", "958"), ("energy_atwater_general", "957")):
            if source in nutrients:
                nutrients["energy"] = nutrients[source]
                filled["energy"] = nbr
                break
    if (data_type == "foundation_food" and "folate" not in nutrients and "folate_total" in nutrients
            and fdc_id not in FOLATE_TOTAL_EXCLUDED):
        nutrients["folate"] = nutrients["folate_total"]
        filled["folate"] = "417"
    return filled


def file_sha256(path: Path = EXTRACT_PATH) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True)
class Backfill:
    fdc_id: int
    name: str
    nutrient_key: str
    amount: float
    source_nbr: str


def build_rows(foundation_dir: Path) -> list[Backfill]:
    """Every value apply_fallbacks fills for a Foundation row ingest_fdc.py
    keeps (one with protein)."""
    from .ingest_fdc import build_amino_acid_profile, load_foods, load_nutrient_amounts, load_nutrient_id_to_nbr

    foods = {k: v for k, v in load_foods(foundation_dir / "food.csv").items() if v["data_type"] == "foundation_food"}
    nbr = load_nutrient_id_to_nbr(foundation_dir / "nutrient.csv")
    amounts = load_nutrient_amounts(foundation_dir / "food_nutrient.csv", nbr, set(foods))
    missing = sorted(set(map(str, FOLATE_TOTAL_EXCLUDED)) - set(foods))
    if missing:
        raise SystemExit(f"excluded fdc_ids not in {foundation_dir}: {missing}")
    rows = []
    for fdc_id in sorted(foods, key=int):
        nutrients = dict(amounts.get(fdc_id, {}))
        if build_amino_acid_profile(nutrients) is None:
            continue  # ingest skips it
        for key, source in sorted(apply_fallbacks(int(fdc_id), "foundation_food", nutrients).items()):
            rows.append(Backfill(int(fdc_id), foods[fdc_id]["name"], key, nutrients[key], source))
    return rows


def render(rows: list[Backfill]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for r in rows:
        writer.writerow((r.fdc_id, r.name, r.nutrient_key, repr(r.amount), r.source_nbr))
    return buf.getvalue()


def load_extract(path: Path = EXTRACT_PATH) -> list[Backfill]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"{path.name}: header must be {','.join(COLUMNS)}")
    return [Backfill(int(r["fdc_id"]), r["name"], r["nutrient_key"], float(r["amount_per_100g"]),
                     r["source_nutrient_nbr"]) for r in reader]


@dataclass
class ApplyResult:
    inserted: int = 0
    already_present: int = 0
    food_missing: int = 0
    name_mismatch: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    def summary(self) -> str:
        if self.skipped_reason:
            return f"foundation nutrients: skipped ({self.skipped_reason})"
        return (f"foundation nutrients: {self.inserted} inserted, {self.already_present} already present, "
                f"{self.food_missing} for foods not in this catalogue, {len(self.name_mismatch)} name mismatches")


def apply(db: Session, rows: list[Backfill]) -> ApplyResult:
    """Insert each extract value whose Foundation food is present under the
    same name and has no row for that nutrient yet. Never changes an
    existing nutrient row. A food under another name (a different FDC
    release) is skipped and reported, not guessed at."""
    if db.execute(select(Food.id).where(Food.fdc_id.isnot(None)).limit(1)).first() is None:
        return ApplyResult(skipped_reason="no FDC catalogue rows")
    result = ApplyResult()
    foods = {f.fdc_id: f for f in db.execute(select(Food).where(
        Food.fdc_id.in_({r.fdc_id for r in rows}), Food.data_type == "foundation_food")).scalars()}
    existing = set(db.execute(select(FoodNutrient.food_id, FoodNutrient.nutrient_key).where(
        FoodNutrient.food_id.in_([f.id for f in foods.values()]))).tuples())
    for r in rows:
        food = foods.get(r.fdc_id)
        if food is None:
            result.food_missing += 1
            continue
        if food.name != r.name:
            result.name_mismatch.append(f"{r.fdc_id}: catalogue {food.name!r}, extract {r.name!r}")
            continue
        if (food.id, r.nutrient_key) in existing:
            result.already_present += 1
            continue
        db.add(FoodNutrient(food_id=food.id, nutrient_key=r.nutrient_key, amount_per_100g=r.amount))
        existing.add((food.id, r.nutrient_key))
        result.inserted += 1
    db.flush()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.foundation_nutrients", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        sub.add_parser(name).add_argument("--foundation-dir", type=Path, required=True)
    sub.add_parser("load").add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "load":
        from .database import SessionLocal

        db = SessionLocal()
        try:
            result = apply(db, load_extract())
            print(result.summary())
            for line in result.name_mismatch:
                print(f"  name mismatch: {line}")
            db.rollback() if args.dry_run else db.commit()
        finally:
            db.close()
        return 0
    text = render(build_rows(args.foundation_dir))
    if args.command == "build":
        EXTRACT_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {EXTRACT_PATH.name}: {text.count(chr(10)) - 1} values, sha256 {file_sha256()}")
        return 0
    if EXTRACT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
        print(f"{EXTRACT_PATH.name} differs from the export", file=sys.stderr)
        return 1
    print(f"{EXTRACT_PATH.name} matches the export (sha256 {file_sha256()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
