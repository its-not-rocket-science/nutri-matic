"""Backfills amino acid composition onto specific existing Food rows whose
FDC record has no amino acid data at all, using real published values from
elsewhere — not FDC, and not a broad category estimate the way
digestibility_reference.py's CATEGORY_FALLBACK works (a per-amino-acid
profile genuinely varies food to food; there's no safe "vegetable average"
the way a single digestibility coefficient can be approximated).

Only touches Food rows matched by exact name where every listed amino acid
key is currently null — never overwrites a food that already has some or
all of its profile, and never touches a food not explicitly listed here.
Each entry's amino_acids dict may be partial (a key simply absent means
"not reported by this source, leave it null downstream" — the same
convention scoring.py already handles for FDC-sourced foods missing an
amino acid).

Usage:
    python -m app.patch_amino_acid_data [--dry-run]
"""

import argparse

from .database import SessionLocal
from .models import Food
from .reference_patterns import AMINO_ACIDS

# name -> (amino_acids partial dict, citation). Values are mg per g protein,
# same unit convention as every FDC-derived Food.amino_acids entry.
PATCHES: dict[str, tuple[dict[str, float], str]] = {
    "Onions, red, raw": (
        {
            "histidine": 16.67, "isoleucine": 18.18, "leucine": 29.49, "lysine": 23.28,
            "met_cys": 0.33, "phe_tyr": 46.55, "threonine": 40.03, "valine": 23.75,
            # tryptophan not reported by the source — left absent, same
            # convention as e.g. digestibility_reference.py's Kashyap et
            # al. egg/chicken entries
        },
        "Derived from Bagheri et al. 2020, 'Comparison of Organosulfur and "
        "Amino Acid Composition between Triploid Onion Allium cornutum... "
        "and Common Onion Allium cepa L.', PMC7020437, Table 2 (mg/g dry "
        "weight for A. cepa) — converted to mg/g protein using this "
        "database's own ingested USDA protein content for 'Onions, raw' "
        "(1.1 g/100g fresh) and USDA's widely reported ~89% raw-onion "
        "moisture content (i.e. 11 g dry matter/100g fresh, so protein is "
        "~10% of dry matter): mg/g_DW / 0.10 = mg/g_protein. This "
        "conversion is a derived estimate, not a value either source "
        "reports directly — flagged here rather than silently presented "
        "as a single clean measurement.",
    ),
    "Onions, raw": (
        {
            "histidine": 16.67, "isoleucine": 18.18, "leucine": 29.49, "lysine": 23.28,
            "met_cys": 0.33, "phe_tyr": 46.55, "threonine": 40.03, "valine": 23.75,
        },
        "Same source/derivation as 'Onions, red, raw' above — the source "
        "paper's common-onion sample is not colour-specific, and this "
        "database's own generic 'Onions, raw' protein content (1.1g/100g) "
        "is what the conversion is already based on.",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for name, (amino_acids, _citation) in PATCHES.items():
        unknown_keys = set(amino_acids) - set(AMINO_ACIDS)
        if unknown_keys:
            raise ValueError(f"{name}: unknown amino acid key(s) {unknown_keys}")

    db = SessionLocal()
    try:
        patched, skipped_has_data, skipped_not_found = 0, 0, 0
        for name, (amino_acids, citation) in PATCHES.items():
            food = db.query(Food).filter(Food.name == name).one_or_none()
            if food is None:
                print(f"skip (not found): {name}")
                skipped_not_found += 1
                continue
            if any(food.amino_acids.get(aa) is not None for aa in amino_acids):
                print(f"skip (already has some data): {name}")
                skipped_has_data += 1
                continue

            merged = dict(food.amino_acids)
            merged.update(amino_acids)
            print(f"patch: {name} (id={food.id}) — {citation[:80]}...")
            if not args.dry_run:
                food.amino_acids = merged
            patched += 1

        if not args.dry_run:
            db.commit()
        print(f"patched={patched} skipped_has_data={skipped_has_data} skipped_not_found={skipped_not_found}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
