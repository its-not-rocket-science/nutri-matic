"""One-off ingestion script for phytate compound observations (prompts.txt
Prompt 3 of the phytate/mineral-bioavailability extension) — populates
CompoundObservation rows with compound="phytate" from a normalised
intermediate CSV.

STATUS — placeholder input format. The intended real source, FAO/
INFOODS/IZiNCG PhyFoodComp1.0, is blocked on an unresolved licence
question (see docs/phytate-evidence-review.md); its actual file has not
been obtained, so this script cannot yet parse PhyFoodComp's own column
layout. What IS built and tested here is everything downstream of
parsing: honest match-confidence assignment (Prompt 3 rule 2),
needs-review flagging (rule 3), and idempotent re-ingestion (rule 4) —
the parts that don't change once a real file is in hand. When the
licence is resolved, add a thin adapter mapping PhyFoodComp's actual
columns into load_rows()'s RawObservation shape below; nothing else in
this file should need to change as a result.

Usage:
    python -m app.ingest_phytate --csv path/to/phytate_rows.csv \
        --dataset-name "PhyFoodComp1.0" \
        --dataset-citation "FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0." \
        --dataset-version "1.0" --access-date 2026-08-01

Input CSV columns (see RawObservation): food_description, value, unit,
basis (required); preparation_state, compound_fraction,
analytical_method, row_identifier (optional, blank if absent).

Matching reuses this app's existing food-matching infrastructure
(app.stock_recipes.food_matching.match_ingredient — the same fuzzy/
alias/canonical search stock-recipe ingredient matching already uses)
rather than a parallel fuzzy matcher, per the ground rules. Confidence
is assigned honestly here, not inherited wholesale from that
infrastructure: match_ingredient's "canonical"/"fuzzy" methods only tell
us a food NAME matches, not that cultivar, processing state, and
moisture basis all line up too — the things that actually matter for a
phytate value's correctness (see docs/phytate-evidence-review.md's
cross-study-noise warning). "exact" is never assigned automatically by
this script — see classify_match's docstring for why.
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from .database import Base, SessionLocal, engine
from .models import CompoundObservation
from .search import search_foods_by_name
from .stock_recipes.food_matching import MatchResult, match_ingredient

COMPOUND = "phytate"

# Below this match_ingredient confidence, a candidate is not trusted
# enough to auto-classify at all — flagged needs_review regardless of
# how the rest of classify_match would otherwise have scored it.
NEEDS_REVIEW_CONFIDENCE_THRESHOLD = 0.55
# If the top two name-search candidates' text similarity to the source
# description are within this margin of each other, the match is
# genuinely ambiguous — flagged needs_review even if the chosen match's
# own confidence alone would have cleared the threshold above. Computed
# independently of match_ingredient's MatchCandidate.score, which is a
# fixed rank-based placeholder (1.0, 0.92, 0.84, ...) rather than a real
# similarity measure — see _ambiguous_candidates.
AMBIGUOUS_SIMILARITY_MARGIN = 0.1
# At or above this confidence (with basis/preparation-state alignment
# NOT confirmed — see classify_match), a match is trusted as a
# reasonable but unverified analogue rather than downgraded to the
# coarser category_proxy tier.
CLOSE_ANALOGUE_MIN_CONFIDENCE = 0.7

EDIBLE_PORTION_BASIS = "per_100g_edible_portion"


@dataclass
class RawObservation:
    """One row of the placeholder intermediate CSV format — see module
    docstring. Deliberately shaped like CompoundObservation's own
    source_* fields, so mapping a real PhyFoodComp adapter's output into
    this later is a straight field-for-field job."""

    food_description: str
    value: float
    unit: str
    basis: str
    preparation_state: str | None = None
    compound_fraction: str | None = None
    analytical_method: str | None = None
    row_identifier: str | None = None


def load_rows(csv_path: Path) -> list[RawObservation]:
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for line in csv.DictReader(f):
            rows.append(RawObservation(
                food_description=line["food_description"].strip(),
                value=float(line["value"]),
                unit=line["unit"].strip(),
                basis=line["basis"].strip(),
                preparation_state=(line.get("preparation_state") or "").strip() or None,
                compound_fraction=(line.get("compound_fraction") or "").strip() or None,
                analytical_method=(line.get("analytical_method") or "").strip() or None,
                row_identifier=(line.get("row_identifier") or "").strip() or None,
            ))
    return rows


def _ambiguous_candidates(db, description: str) -> tuple[bool, str | None]:
    """True (plus an explanatory rationale) when the top two name-search
    candidates are too textually similar to the source description, and
    to each other, to place confidently — computed independently of
    match_ingredient's own candidate scores, which are a fixed rank-based
    placeholder rather than a real similarity measure (see
    AMBIGUOUS_SIMILARITY_MARGIN). Reuses search_foods_by_name, this app's
    existing fuzzy-search service, rather than a new one."""
    candidates = search_foods_by_name(db, description, limit=2)
    if len(candidates) < 2:
        return False, None

    def similarity(name: str) -> float:
        return SequenceMatcher(None, description.strip().lower(), name.lower()).ratio()

    top, runner_up = candidates[0], candidates[1]
    top_score, runner_up_score = similarity(top.name), similarity(runner_up.name)
    if (top_score - runner_up_score) < AMBIGUOUS_SIMILARITY_MARGIN:
        return True, (
            f"top two name-search candidates ({top.name!r}, {runner_up.name!r}) are too textually similar "
            f"to the source description ({top_score:.2f} vs {runner_up_score:.2f} similarity) to place confidently"
        )
    return False, None


def classify_match(
    db, match: MatchResult, description: str, preparation_state: str | None, basis: str,
) -> tuple[str, str]:
    """Maps a MatchResult from the app's existing food-matching
    infrastructure onto this table's honest match_relationship vocabulary
    (prompts.txt Prompt 3 rule 2). Never returns "exact": match_ingredient
    can tell us a food NAME matches, but PhyFoodComp entries can share a
    name with an FDC food while differing in cultivar, processing, or
    moisture basis — "exact" is reserved for a mapping a human has
    actually verified against the source, which this script has no way
    to do on its own.
    """
    if match.food is None:
        return "needs_review", "no FDC candidate found for this source description"

    ambiguous, ambiguous_rationale = _ambiguous_candidates(db, description)
    if ambiguous:
        return "needs_review", ambiguous_rationale

    confidence = match.confidence or 0.0
    if confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD:
        return "needs_review", (
            f"match confidence {confidence:.2f} below the {NEEDS_REVIEW_CONFIDENCE_THRESHOLD} needs-review threshold"
        )

    prep_aligned = bool(preparation_state) and preparation_state.strip().lower() in match.food.name.lower()
    if prep_aligned and basis == EDIBLE_PORTION_BASIS:
        return "regional_equivalent", (
            f"name match with preparation state {preparation_state!r} confirmed present in "
            f"{match.food.name!r}, and matching edible-portion basis — not human-verified, so capped "
            "below 'exact'"
        )

    if confidence >= CLOSE_ANALOGUE_MIN_CONFIDENCE:
        return "close_analogue", (
            f"name-matched at confidence {confidence:.2f}, but preparation state/moisture basis alignment "
            "could not be confirmed automatically"
        )

    return "category_proxy", f"weak name match (confidence {confidence:.2f}) taken as a coarse stand-in only"


def ingest_rows(
    db, rows: list[RawObservation], dataset_name: str, dataset_citation: str, dataset_version: str,
    access_date: date, dry_run: bool,
) -> dict:
    stats = {"considered": 0, "inserted": 0, "updated": 0, "needs_review": 0}
    needs_review_samples: list[dict] = []

    for row in rows:
        stats["considered"] += 1
        match = match_ingredient(db, row.food_description)
        relationship, rationale = classify_match(db, match, row.food_description, row.preparation_state, row.basis)
        matched_food_id = match.food.id if match.food is not None else None

        if relationship == "needs_review":
            stats["needs_review"] += 1
            if len(needs_review_samples) < 20:
                needs_review_samples.append({
                    "food_description": row.food_description, "row_identifier": row.row_identifier,
                    "candidate": match.food.name if match.food else None, "rationale": rationale,
                })

        if dry_run:
            continue

        existing = (
            db.query(CompoundObservation)
            .filter(
                CompoundObservation.compound == COMPOUND,
                CompoundObservation.source_dataset_name == dataset_name,
                CompoundObservation.source_dataset_version == dataset_version,
                CompoundObservation.source_row_identifier == row.row_identifier,
            )
            .one_or_none()
            if row.row_identifier is not None
            else None
        )

        fields = dict(
            compound=COMPOUND,
            compound_fraction=row.compound_fraction,
            original_value=row.value,
            original_unit=row.unit,
            original_basis=row.basis,
            source_food_description=row.food_description,
            source_preparation_state=row.preparation_state,
            source_dataset_name=dataset_name,
            source_dataset_citation=dataset_citation,
            source_dataset_version=dataset_version,
            source_access_date=access_date,
            analytical_method=row.analytical_method,
            source_row_identifier=row.row_identifier,
            match_relationship=relationship,
            match_confidence=match.confidence,
            match_rationale=rationale,
            matched_food_id=matched_food_id,
        )

        if existing is None:
            db.add(CompoundObservation(**fields))
            stats["inserted"] += 1
        else:
            for key, value in fields.items():
                setattr(existing, key, value)
            stats["updated"] += 1

    if not dry_run:
        db.commit()

    return stats, needs_review_samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, help="Path to the intermediate phytate-rows CSV (see module docstring)")
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-citation", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--access-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Parse and classify without writing to the DB")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"error: not a file: {csv_path}", file=sys.stderr)
        sys.exit(1)
    access_date = datetime.strptime(args.access_date, "%Y-%m-%d").date()

    if not args.dry_run:
        Base.metadata.create_all(bind=engine)

    rows = load_rows(csv_path)
    db = SessionLocal()
    try:
        stats, needs_review_samples = ingest_rows(
            db, rows, args.dataset_name, args.dataset_citation, args.dataset_version, access_date, args.dry_run,
        )
    finally:
        db.close()

    print(
        f"considered={stats['considered']} inserted={stats['inserted']} updated={stats['updated']} "
        f"needs_review={stats['needs_review']}"
    )
    if needs_review_samples:
        print(f"\nneeds_review sample ({len(needs_review_samples)} of {stats['needs_review']}):")
        for sample in needs_review_samples:
            print(f"  {sample}")


if __name__ == "__main__":
    main()
