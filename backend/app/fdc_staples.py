"""Everyday protein-free SR Legacy foods that ingest_fdc.py skips.

ingest_fdc.py skips every FDC row without a usable protein value, because
it builds an amino-acid profile per gram of protein. That leaves the
catalogue with no white sugar, cooking oil, table salt, vinegar, plain tea
or water, which everyday UK logging needs (canonical foods plan, PR 4b
review). This module adds a reviewed shortlist of those rows as real
`sr_legacy_food` rows with their FDC ids, exactly as ingest_fdc.py would
have written them had it not skipped them:

  * name, fdc_id and data_type from SR Legacy's food.csv;
  * protein_g_per_100g = the reported protein, or 0.0 if none;
  * amino_acids = every key present and null, the "incomplete profile"
    every branded row already has (aggregation.py skips zero-protein
    ingredients before it looks at amino acids, see seed_manual_foods.py);
  * one FoodNutrient row per nutrients.NUTRIENTS key SR reports, with the
    same fibre fallback ingest_fdc.py applies.

Source: USDA FoodData Central, SR Legacy, April 2018 CSV export
(FoodData_Central_sr_legacy_food_csv_2018-04.zip, sha256 SR_ZIP_SHA256),
public domain (docs/fdc-provenance.md). The raw export is git-ignored, so
the committed extract (fdc_staples_sr_legacy_2018_04.csv) is what
production loads. Rebuild it from the export with

    python -m app.fdc_staples build --sr-dir data/sr_legacy/FoodData_Central_sr_legacy_food_csv_2018-04

and `python -m app.fdc_staples verify --sr-dir ...` checks the committed
file against the export byte for byte.

Production loads it through an Alembic data migration pinned to the
extract's sha256 (owner's decision, as for the canonical CSV). Inserting
rows changes the catalogue snapshot checksum (catalogue_manifest.py), so
re-run app.resolve_phytate_stable_ids before the next phytate import.
Existing rows keep their id and fdc_id, so the resolved targets do not
change. Nothing at runtime reads that checksum.
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
from .nutrients import NUTRIENTS
from .reference_patterns import AMINO_ACIDS

EXTRACT_PATH = Path(__file__).resolve().parent / "fdc_staples_sr_legacy_2018_04.csv"
SR_ZIP_SHA256 = "b80817294b8850530aaedf2e515c02593b1824f763a0ff356e5c2081643e6fd0"
COLUMNS = ("fdc_id", "data_type", "name", "nutrient_key", "amount_per_100g")
PROTEIN_KEY = "protein"

# The owner-approved shortlist (PR review): fdc_id -> why it is here.
STAPLES: dict[int, str] = {
    169655: "white / caster sugar",
    169656: "icing sugar",
    170674: "demerara-style raw cane sugar",
    171413: "olive oil",
    172336: "rapeseed oil (US canola)",
    171025: "sunflower oil (regular linoleic, as sold in UK shops)",
    171411: "soybean oil",
    171412: "coconut oil",
    171016: "sesame oil",
    171410: "groundnut / peanut oil",
    171029: "corn oil",
    173573: "avocado oil",
    173468: "table salt",
    170276: "maple syrup",
    167743: "cane syrup (closest SR row to golden syrup)",
    168837: "light corn syrup",
    173469: "cider vinegar",
    172237: "distilled (white) vinegar",
    173227: "black tea, brewed",
    173232: "herbal tea, brewed",
    173647: "tap water",
    171401: "lard",
    171400: "beef tallow (dripping)",
}


@dataclass
class StapleFood:
    fdc_id: int
    data_type: str
    name: str
    protein: float
    nutrients: dict[str, float] = field(default_factory=dict)


def file_sha256(path: Path = EXTRACT_PATH) -> str:
    """Checksum with line endings normalised, so Windows and CI agree."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# --- building the extract from the raw export ------------------------------

def build_rows(sr_dir: Path) -> list[StapleFood]:
    from .ingest_fdc import build_amino_acid_profile, load_foods, load_nutrient_amounts, load_nutrient_id_to_nbr

    foods = load_foods(sr_dir / "food.csv")
    missing = sorted(set(map(str, STAPLES)) - set(foods))
    if missing:
        raise SystemExit(f"not in {sr_dir}: {missing}")
    nbr = load_nutrient_id_to_nbr(sr_dir / "nutrient.csv")
    amounts = load_nutrient_amounts(sr_dir / "food_nutrient.csv", nbr, set(map(str, STAPLES)))
    out = []
    for fdc_id in sorted(STAPLES):
        info, nutrients = foods[str(fdc_id)], dict(amounts.get(str(fdc_id), {}))
        if build_amino_acid_profile(nutrients) is not None:
            raise SystemExit(f"{fdc_id} {info['name']!r} has protein; ingest_fdc.py already loads it")
        if "fiber_total" not in nutrients and "fiber_total_aoac" in nutrients:
            nutrients["fiber_total"] = nutrients["fiber_total_aoac"]
        out.append(StapleFood(
            fdc_id, info["data_type"], info["name"], float(nutrients.get("protein") or 0.0),
            {k: nutrients[k] for k in NUTRIENTS if k in nutrients},
        ))
    return out


def render(rows: list[StapleFood]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for food in rows:
        writer.writerow((food.fdc_id, food.data_type, food.name, PROTEIN_KEY, repr(food.protein)))
        for key in sorted(food.nutrients):
            writer.writerow((food.fdc_id, food.data_type, food.name, key, repr(food.nutrients[key])))
    return buf.getvalue()


# --- reading and loading the committed extract -----------------------------

def load_extract(path: Path = EXTRACT_PATH) -> list[StapleFood]:
    reader = csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"{path.name}: header must be {','.join(COLUMNS)}")
    foods: dict[int, StapleFood] = {}
    for row in reader:
        fdc_id = int(row["fdc_id"])
        food = foods.setdefault(fdc_id, StapleFood(fdc_id, row["data_type"], row["name"], 0.0))
        if (food.data_type, food.name) != (row["data_type"], row["name"]):
            raise ValueError(f"{path.name}: fdc_id {fdc_id} has inconsistent name or type")
        amount = float(row["amount_per_100g"])
        if row["nutrient_key"] == PROTEIN_KEY:
            food.protein = amount
        elif row["nutrient_key"] in NUTRIENTS:
            food.nutrients[row["nutrient_key"]] = amount
        else:
            raise ValueError(f"{path.name}: unknown nutrient_key {row['nutrient_key']!r}")
    return list(foods.values())


@dataclass
class ApplyResult:
    inserted: list[int] = field(default_factory=list)
    already_present: list[int] = field(default_factory=list)
    skipped_reason: str | None = None

    def summary(self) -> str:
        if self.skipped_reason:
            return f"fdc staples: skipped ({self.skipped_reason})"
        return f"fdc staples: {len(self.inserted)} inserted, {len(self.already_present)} already present"


def apply(db: Session, foods: list[StapleFood]) -> ApplyResult:
    """Insert each staple whose fdc_id is not in `foods` yet. An existing
    row is left exactly as it is (never updated), so a later full ingest
    or a re-run changes nothing. Skipped on a database with no FDC rows,
    like the canonical load: there is no catalogue to add to."""
    if db.execute(select(Food.id).where(Food.fdc_id.isnot(None)).limit(1)).first() is None:
        return ApplyResult(skipped_reason="no FDC catalogue rows")
    result = ApplyResult()
    present = set(db.execute(select(Food.fdc_id).where(Food.fdc_id.in_([f.fdc_id for f in foods]))).scalars())
    for staple in foods:
        if staple.fdc_id in present:
            result.already_present.append(staple.fdc_id)
            continue
        food = Food(
            name=staple.name, protein_g_per_100g=staple.protein, amino_acids=dict.fromkeys(AMINO_ACIDS),
            fdc_id=staple.fdc_id, data_type=staple.data_type, gtin_upc=None,
        )
        db.add(food)
        db.flush()
        db.add_all(FoodNutrient(food_id=food.id, nutrient_key=k, amount_per_100g=v) for k, v in staple.nutrients.items())
        result.inserted.append(staple.fdc_id)
    db.flush()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.fdc_staples", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (("build", "Write the extract from the raw SR export"),
                        ("verify", "Check the committed extract against the raw SR export")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--sr-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    text = render(build_rows(args.sr_dir))
    if args.command == "build":
        EXTRACT_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {EXTRACT_PATH.name}: {len(STAPLES)} foods, sha256 {file_sha256()}")
        return 0
    if EXTRACT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
        print(f"{EXTRACT_PATH.name} differs from the export", file=sys.stderr)
        return 1
    print(f"{EXTRACT_PATH.name} matches the export (sha256 {file_sha256()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
