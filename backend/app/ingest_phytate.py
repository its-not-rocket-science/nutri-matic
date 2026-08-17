"""One-off ingestion script for phytate compound observations (prompts.txt
Prompt 3 of the phytate/mineral-bioavailability extension) — populates
CompoundObservation rows with compound="phytate", from either a
normalised intermediate CSV (see RawObservation) or a real
PhyFoodComp_1.0.xlsx workbook (via app.phyfoodcomp_adapter).

STATUS — the real file has been obtained and app.phyfoodcomp_adapter
parses its actual column layout (see that module for the workbook
structure). Licence: confirmed non-commercial-only from the workbook's
own embedded copyright notice (see docs/phytate-evidence-review.md §1) —
fine for free-tier/research use with FAO attribution; paid-tier use
needs a separate written answer from FAO. **Do not write real ingested
rows to any database used by a paid tier, and do not merge/ship a real
(non-dry-run) ingestion until both (a) FAO's paid-tier answer arrives
and (b) a human has reviewed the needs-review sample this script
prints** (prompts.txt's Prompt 3 stop point).

PROMPT 3B — two bugs found during the Prompt 3 human review are fixed
here: _ambiguous_candidates no longer mislabels the selected candidate's
own text similarity as "top_similarity" (see its docstring), and
_prefer_infant_cereal_candidate corrects a category-retrieval bug for
"Infant flour, cereal-based, ..." wording variants (see its docstring).
Ingestion must be re-run and the needs_review output regenerated before
the Prompt 3 human-review gate is considered current again — see
prompts.txt's STATUS section.

Usage:
    python -m app.ingest_phytate --csv path/to/phytate_rows.csv \
        --dataset-name "PhyFoodComp1.0" \
        --dataset-citation "FAO/INFOODS/IZiNCG. Global food composition database for phytate, version 1.0." \
        --dataset-version "1.0" --access-date 2026-08-01

    python -m app.ingest_phytate --xlsx path/to/PhyFoodComp_1.0.xlsx \
        --dataset-name "PhyFoodComp1.0" --dataset-citation "..." \
        --dataset-version "1.0" --access-date 2026-08-05 --dry-run

Input CSV columns (see RawObservation): food_description, value, unit,
basis (required); preparation_state, compound_fraction,
analytical_method, row_identifier (optional, blank if absent). Not
needed for --xlsx, which reads a real workbook directly.

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
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import CompoundObservation, Food
from .stock_recipes.food_matching import MatchCandidate, MatchResult, match_ingredient

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


def _ambiguous_candidates(match: MatchResult, description: str) -> tuple[bool, str | None]:
    """True (plus an explanatory rationale) when the top two name-search
    candidates are too textually similar to the source description, and
    to each other, to place confidently — computed independently of
    match_ingredient's own candidate scores, which are a fixed rank-based
    placeholder rather than a real similarity measure (see
    AMBIGUOUS_SIMILARITY_MARGIN). Reuses match.candidates (already
    populated by match_ingredient's own search_foods_by_name call) rather
    than issuing a second, identical fuzzy-search query — this app's
    fuzzy tier falls back to a Postgres trigram scan that, at the scale
    of the real Food catalog, is expensive enough that a second query per
    observation would double an already-costly path for no benefit.

    Found against the real ~1.4M-row Food catalog: the two top candidates
    are very often the exact same food name twice, or the same name
    differing only in case (duplicate/near-duplicate Branded Foods
    catalog rows — different pack sizes or listings, identical
    description text). Comparing each candidate's similarity only to the
    query, as an earlier version of this function did, treated every one
    of those as "ambiguous" — trivially true (identical names score
    identically) but not meaningful, since picking either candidate gives
    the same answer. Checked first, before the query-similarity
    comparison, so it can short-circuit that false-positive pattern.

    Deliberately an exact (case-insensitive) equality check, not a fuzzy
    similarity threshold: an earlier attempt at the latter (>=0.9
    candidate-to-candidate similarity) also swallowed genuinely different
    foods that happen to share most of their name — "Beans, kidney,
    red..." vs "...white..." differs by exactly as much text as two
    duplicate SKUs differing by pack size, so a fuzzy threshold can't
    tell them apart. Exact-text duplicates can be resolved safely; a
    near-duplicate that isn't byte-for-byte identical (e.g. two pack
    sizes with different unit text) still falls through to the
    similarity-margin check below, erring toward needs_review rather than
    risking a masked genuine difference.

    PROMPT 3B bug 1 fix: this compares match.candidates[0] ("selected" —
    match_ingredient's own top-ranked/chosen candidate) against
    match.candidates[1] ("runner_up"), same pair and same trigger
    arithmetic as before (so which rows get flagged needs_review is
    unchanged) — the bug was purely in how the result got reported
    downstream. The old code called candidates[0]'s score "top_similarity"
    unconditionally, which is wrong whenever the runner-up's text
    similarity is actually higher: a row could report top_similarity=0.81
    for the selected candidate while the runner-up scored 0.82 — a higher
    score hiding under a name that implied it couldn't exist. Confirmed in
    238/794 reviewed rows (see
    docs/phytate-review/prompt3b_bug_evidence_and_fixtures.csv). Now the
    rationale always names both the selected candidate's own similarity
    and whichever of the two candidates actually scores highest, so the
    gap between "selected" and "best available" is never silently
    dropped."""
    if len(match.candidates) < 2:
        return False, None

    def similarity(name: str) -> float:
        return SequenceMatcher(None, description.strip().lower(), name.lower()).ratio()

    selected, runner_up = match.candidates[0], match.candidates[1]
    if selected.name.lower() == runner_up.name.lower():
        return False, None

    selected_similarity = similarity(selected.name)
    runner_up_similarity = similarity(runner_up.name)

    if (selected_similarity - runner_up_similarity) < AMBIGUOUS_SIMILARITY_MARGIN:
        if selected_similarity >= runner_up_similarity:
            best_name, best_similarity = selected.name, selected_similarity
        else:
            best_name, best_similarity = runner_up.name, runner_up_similarity
        selected_is_best = best_name.lower() == selected.name.lower()
        best_note = (
            "" if selected_is_best else
            f" — note: the selected candidate is NOT the highest-similarity one; "
            f"{best_name!r} scored higher"
        )
        return True, (
            f"top two name-search candidates ({selected.name!r} [selected], {runner_up.name!r}) are too "
            f"textually similar to the source description (selected candidate similarity: "
            f"{selected_similarity:.2f}; runner-up similarity: {runner_up_similarity:.2f}; "
            f"best candidate similarity: {best_similarity:.2f}, held by {best_name!r}){best_note} "
            "to place confidently"
        )
    return False, None


_INFANT_OR_BABY_RE = re.compile(r"\b(infant|baby)\b", re.IGNORECASE)
_BABYFOOD_CEREAL_DRY_FORTIFIED_RE = re.compile(r"^Babyfood, cereal,.*dry fortified", re.IGNORECASE)
# Grain words worth trying to match specifically before falling back to
# whatever babyfood-cereal candidate sorts first — see
# _prefer_infant_cereal_candidate.
_GRAIN_WORDS = ("barley", "rice", "oat", "wheat", "corn", "maize", "millet", "rye", "mixed", "multigrain")


def _prefer_infant_cereal_candidate(db: Session, description: str, match: MatchResult) -> MatchResult:
    """PROMPT 3B bug 2 fix. A source description matching /infant|baby/i
    should always prefer FDC's dedicated "Babyfood, cereal, [grain], dry
    fortified" category over whatever the general-purpose fuzzy search
    ranks highest by raw text overlap.

    Confirmed cluster: 93 "Infant flour, cereal-based, ..." rows, where
    the wording "commercially produced" pulled in "Babyfood, baked
    product, finger snacks cereal fortified" (48 rows) and "Pie, apple,
    commercially prepared, enriched flour" (26 rows) — both share the
    incidental phrase "commercially produced/prepared" with the source
    description far more than the actually-correct "Babyfood, cereal,
    ..., dry fortified" entries do, so raw text-overlap ranking picked
    the wrong category outright. The near-identical wording "commercial"
    (no "-ly produced") already found the right category correctly,
    proving the correct candidates exist in FDC — this is a
    retrieval/ranking bug for one wording variant, not a missing-data
    case. See prompts.txt PROMPT 3B and
    docs/phytate-review/review_5_infant_flour_cluster.csv.

    Deliberately narrow and explicit rather than a general retrieval
    overhaul, per PROMPT 3B's own instruction — this queries the babyfood-
    cereal category directly instead of trying to make the general fuzzy
    ranker smarter about category words in general."""
    if not _INFANT_OR_BABY_RE.search(description):
        return match

    if match.food is not None and _BABYFOOD_CEREAL_DRY_FORTIFIED_RE.match(match.food.name):
        return match  # already the right category

    babyfood_cereal_candidates = (
        db.query(Food)
        .filter(Food.name.ilike("Babyfood, cereal,%dry fortified%"))
        .order_by(Food.name)
        .all()
    )
    if not babyfood_cereal_candidates:
        return match

    description_lower = description.lower()
    grain = next((g for g in _GRAIN_WORDS if g in description_lower), None)
    # A description naming no grain at all, or naming one FDC has no
    # dedicated babyfood-cereal candidate for (corn/maize/millet, per the
    # human review in review_5_infant_flour_cluster.csv/
    # review_6_accepted_sample.csv/review_6b_accepted_remainder.csv —
    # FDC only has barley/mixed/oatmeal/rice/multigrain), must not fall
    # back to whichever candidate sorts first alphabetically (barley) —
    # that's an arbitrary, wrong single-grain claim the source never
    # made. The honest fallback is the mixed-grain generic.
    mixed_candidate = next((f for f in babyfood_cereal_candidates if "mixed" in f.name.lower()), None)
    chosen = next(
        (f for f in babyfood_cereal_candidates if grain and grain in f.name.lower()),
        mixed_candidate or babyfood_cereal_candidates[0],
    )

    new_candidates = [MatchCandidate(food_id=chosen.id, name=chosen.name, score=1.0)] + [
        c for c in match.candidates if c.food_id != chosen.id
    ]
    return MatchResult(
        food=chosen,
        method="category_override",
        confidence=max(match.confidence or 0.0, CLOSE_ANALOGUE_MIN_CONFIDENCE),
        candidates=new_candidates,
    )


def classify_match(match: MatchResult, description: str, preparation_state: str | None, basis: str) -> tuple[str, str]:
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

    ambiguous, ambiguous_rationale = _ambiguous_candidates(match, description)
    if ambiguous:
        return "needs_review", ambiguous_rationale

    confidence = match.confidence or 0.0
    if confidence < NEEDS_REVIEW_CONFIDENCE_THRESHOLD:
        return "needs_review", (
            f"match confidence {confidence:.2f} below the {NEEDS_REVIEW_CONFIDENCE_THRESHOLD} needs-review threshold"
        )

    prep_aligned = bool(preparation_state) and re.search(
        rf"\b{re.escape(preparation_state.strip().lower())}\b", match.food.name.lower()
    ) is not None
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
    # a single PhyFoodComp food entry commonly yields several
    # RawObservation rows (one per populated tagname column) sharing the
    # exact same food_description — cached so match_ingredient's fuzzy
    # search (an expensive Postgres trigram scan against this app's real
    # Food catalog) only runs once per distinct description, not once per
    # observation.
    match_cache: dict[str, MatchResult] = {}
    # existing's query below won't see a row added earlier in this same
    # loop -- db is SessionLocal, which runs with autoflush=False (see
    # database.py) so a pending db.add() isn't visible to a query until
    # the next explicit flush/commit. Two input rows sharing a
    # row_identifier (duplicate/malformed source data) would otherwise
    # both be treated as new, and the later db.add() would violate
    # uq_compound_observation_source_row at commit time and roll back
    # the whole batch instead of updating in place. Tracked here so the
    # second row updates the first row's in-memory object directly.
    pending_by_identifier: dict[str, CompoundObservation] = {}

    for row in rows:
        stats["considered"] += 1
        match = match_cache.get(row.food_description)
        if match is None:
            match = match_ingredient(db, row.food_description)
            match = _prefer_infant_cereal_candidate(db, row.food_description, match)
            match_cache[row.food_description] = match
        relationship, rationale = classify_match(match, row.food_description, row.preparation_state, row.basis)
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

        existing = None
        if row.row_identifier is not None:
            existing = pending_by_identifier.get(row.row_identifier)
            if existing is None:
                existing = (
                    db.query(CompoundObservation)
                    .filter(
                        CompoundObservation.compound == COMPOUND,
                        CompoundObservation.source_dataset_name == dataset_name,
                        CompoundObservation.source_dataset_version == dataset_version,
                        CompoundObservation.source_row_identifier == row.row_identifier,
                    )
                    .one_or_none()
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
            obs = CompoundObservation(**fields)
            db.add(obs)
            stats["inserted"] += 1
        else:
            obs = existing
            for key, value in fields.items():
                setattr(obs, key, value)
            stats["updated"] += 1

        if row.row_identifier is not None:
            pending_by_identifier[row.row_identifier] = obs

    if not dry_run:
        db.commit()

    return stats, needs_review_samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", help="Path to the intermediate phytate-rows CSV (see module docstring)")
    source.add_argument(
        "--xlsx", help="Path to a real PhyFoodComp_1.0.xlsx (see app.phyfoodcomp_adapter)",
    )
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-citation", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--access-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Parse and classify without writing to the DB")
    args = parser.parse_args()

    access_date = datetime.strptime(args.access_date, "%Y-%m-%d").date()

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.is_file():
            print(f"error: not a file: {csv_path}", file=sys.stderr)
            sys.exit(1)
        rows = load_rows(csv_path)
    else:
        from .phyfoodcomp_adapter import load_phyfoodcomp_workbook
        xlsx_path = Path(args.xlsx)
        if not xlsx_path.is_file():
            print(f"error: not a file: {xlsx_path}", file=sys.stderr)
            sys.exit(1)
        rows, adapter_stats = load_phyfoodcomp_workbook(xlsx_path)
        print(
            f"parsed workbook: sheets={adapter_stats['sheets']} rows_considered={adapter_stats['rows_considered']} "
            f"rows_skipped_no_description={adapter_stats['rows_skipped_no_description']} "
            f"values_skipped_non_numeric={adapter_stats['values_skipped_non_numeric']} "
            f"observations_built={adapter_stats['observations_built']}"
        )

    if not args.dry_run:
        Base.metadata.create_all(bind=engine)

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
