"""Orchestrates the 9 CLI stages against a local JSON candidate cache.

Only `import-approved` and `refresh` ever touch the database — every
earlier stage (discover/fetch/parse/match/analyse/review-export) reads and
writes candidate state under --cache-dir, so a maintainer can inspect,
rerun, or hand-edit any stage's output before anything is published. This
is also what makes every stage safely rerunnable: rerunning `fetch` skips
anything already cached on disk (see sources/schema_org.py), and rerunning
any later stage just recomputes that candidate's fields from scratch.

Candidate cache shape (<cache-dir>/candidates.json): {slug: candidate},
where a candidate is a plain JSON-able dict carrying every field prompt
section 14 wants in a review file, plus the pipeline's own stock_status.
See _new_candidate() for the exact shape.
"""

from __future__ import annotations

import csv
import json
import logging
import secrets
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .. import models
from ..auth import hash_password
from ..database import SessionLocal
from . import dedup
from .collections_config import COLLECTIONS
from .food_matching import MatchResult, compute_coverage, match_ingredient
from .ingredient_parser import PARSER_VERSION, ParsedIngredient, parse_ingredient_lines
from .manifest import ManifestEntry, load_manifest, load_manual_recipes
from .robustness import (
    DEFAULT_RANDOM_SEED,
    DEFAULT_SIMULATION_COUNT,
    RobustnessAnalysis,
    RobustnessIngredientInput,
    estimate_bound_fraction,
    run_robustness,
)
from .sources import RawRecipe, SourceUnavailable, build_adapters
from .suitability import compute_suitability_collections
from .unit_conversion import convert

logger = logging.getLogger(__name__)

DEFAULT_MINIMUM_MATCH_COVERAGE = 0.75
SYSTEM_USER_EMAIL = "stock-recipes@nutrimatic.system"
CANDIDATES_FILENAME = "candidates.json"

_ACTIVE_STATUSES = ("discovered", "parsed", "matched", "needs_review")


# --- candidate cache I/O -------------------------------------------------

def _cache_path(cache_dir: Path) -> Path:
    return cache_dir / CANDIDATES_FILENAME


def _load_cache(cache_dir: Path) -> dict[str, dict]:
    path = _cache_path(cache_dir)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_cache(cache_dir: Path, cache: dict[str, dict]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(cache_dir), "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _new_candidate(entry: ManifestEntry) -> dict:
    return {
        "slug": entry.slug,
        "name": entry.name,
        "collections": entry.collections,
        "source": entry.source,
        "source_name": entry.source_name if entry.source == "fetch" else "manual",
        "source_url": entry.source_url,
        "dietary_characteristics": entry.dietary_characteristics,
        "educational_note": entry.educational_note,
        "priority": entry.priority,
        "notes": entry.notes,
        "stock_status": "discovered",
        "status_reason": None,
        "servings": None,
        "raw_ingredient_lines": None,
        "content_fingerprint": None,
        "retrieved_at": None,
        "source_licence": None,
        "parsed_ingredients": None,
        "matches": None,
        "match_coverage_lines": None,
        "match_coverage_mass": None,
        "unresolved_ingredients": [],
        "nutrition_summary": None,
        "robustness": None,
        "duplicate_candidates": [],
        "computed_collections": [],
        "proposed_publication_status": "needs_review",
        "imported_recipe_id": None,
    }


def _filtered_entries(args) -> list[ManifestEntry]:
    entries = load_manifest()
    if args.source:
        entries = [e for e in entries if (e.source_name or "manual") == args.source]
    if args.collection:
        entries = [e for e in entries if args.collection in e.collections]
    if args.limit:
        entries = entries[: args.limit]
    return entries


def _filtered_candidates(cache: dict[str, dict], args, statuses: tuple[str, ...]) -> list[dict]:
    candidates = [c for c in cache.values() if c["stock_status"] in statuses]
    if args.source:
        candidates = [c for c in candidates if c["source_name"] == args.source]
    if args.collection:
        candidates = [c for c in candidates if args.collection in c["collections"]]
    if args.limit:
        candidates = candidates[: args.limit]
    return candidates


# --- stage: discover -------------------------------------------------------

def cmd_discover(args) -> int:
    entries = _filtered_entries(args)
    cache = _load_cache(args.cache_dir)
    added = 0
    for entry in entries:
        if entry.slug in cache:
            continue
        cache[entry.slug] = _new_candidate(entry)
        added += 1
    _save_cache(args.cache_dir, cache)
    logger.info(
        "discover: %d manifest entries considered, %d new candidates registered, %d already known",
        len(entries), added, len(entries) - added,
    )
    return 0


# --- stage: fetch -----------------------------------------------------------

def cmd_fetch(args) -> int:
    entries_by_slug = {e.slug: e for e in load_manifest()}
    manual_recipes = load_manual_recipes()
    adapters = build_adapters(manual_recipes)

    cache = _load_cache(args.cache_dir)
    # "source_unavailable" is retried too, not just "discovered" — the
    # underlying cause (e.g. a manual entry not yet authored, or a
    # transient live-source failure) may since have been fixed, and
    # leaving it stuck on the first failure forever would defeat --source
    # manual being safely rerunnable after adding more manual_recipes.json
    # entries
    targets = _filtered_candidates(cache, args, ("discovered", "source_unavailable"))
    targets = [c for c in targets if not c["raw_ingredient_lines"]]

    stats = {"attempted": 0, "fetched": 0, "cache_hit": 0, "unavailable": 0}
    for cand in targets:
        entry = entries_by_slug.get(cand["slug"])
        if entry is None:
            continue
        adapter_name = "manual" if entry.source == "manual" else entry.source_name
        adapter = adapters.get(adapter_name)
        stats["attempted"] += 1
        if adapter is None:
            cand["stock_status"] = "source_unavailable"
            cand["status_reason"] = f"no adapter registered for source_name={adapter_name!r}"
            stats["unavailable"] += 1
            continue

        cache_hit = (
            adapter_name != "manual"
            and entry.source_url
            and _page_cached(args.cache_dir, entry.source_url)
            and not getattr(args, "force_refresh", False)
        )
        try:
            raw: RawRecipe = adapter.fetch(entry, args.cache_dir, force_refresh=getattr(args, "force_refresh", False))
        except SourceUnavailable as e:
            cand["stock_status"] = "source_unavailable"
            cand["status_reason"] = str(e)
            stats["unavailable"] += 1
            continue

        if getattr(args, "dry_run", False):
            stats["fetched"] += 1
            continue

        cand["servings"] = raw.servings
        cand["raw_ingredient_lines"] = raw.ingredient_lines
        cand["content_fingerprint"] = raw.content_fingerprint
        cand["source_licence"] = raw.source_licence
        cand["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        # a retried candidate may have been sitting at "source_unavailable"
        # from an earlier run — a successful fetch clears that so `parse`
        # (which only looks at "discovered") picks it up
        cand["stock_status"] = "discovered"
        cand["status_reason"] = None
        stats["cache_hit" if cache_hit else "fetched"] += 1

    _save_cache(args.cache_dir, cache)
    logger.info(
        "fetch: attempted=%d fetched=%d cache_hit=%d source_unavailable=%d",
        stats["attempted"], stats["fetched"], stats["cache_hit"], stats["unavailable"],
    )
    return 0


def _page_cached(cache_dir: Path, url: str) -> bool:
    from .sources.schema_org import SchemaOrgJsonLdAdapter

    return SchemaOrgJsonLdAdapter._cache_path(cache_dir, url).exists()


# --- stage: parse -----------------------------------------------------------

def cmd_parse(args) -> int:
    cache = _load_cache(args.cache_dir)
    targets = _filtered_candidates(cache, args, ("discovered",))
    targets = [c for c in targets if c["raw_ingredient_lines"]]

    stats = {"attempted": 0, "parsed": 0, "rejected": 0}
    for cand in targets:
        stats["attempted"] += 1
        parsed = parse_ingredient_lines(cand["raw_ingredient_lines"])
        usable = [p for p in parsed if p.parsing_confidence > 0.0 and p.name]
        if not usable:
            cand["stock_status"] = "rejected"
            cand["status_reason"] = "no ingredient line could be parsed"
            stats["rejected"] += 1
            continue
        cand["parsed_ingredients"] = [asdict(p) for p in parsed]
        cand["stock_status"] = "parsed"
        stats["parsed"] += 1

    _save_cache(args.cache_dir, cache)
    logger.info("parse: attempted=%d parsed=%d rejected=%d", stats["attempted"], stats["parsed"], stats["rejected"])
    return 0


# --- stage: match -----------------------------------------------------------

def cmd_match(args) -> int:
    min_coverage = getattr(args, "minimum_match_coverage", DEFAULT_MINIMUM_MATCH_COVERAGE)
    cache = _load_cache(args.cache_dir)
    targets = _filtered_candidates(cache, args, ("parsed",))

    db = SessionLocal()
    stats = {"attempted": 0, "matched": 0, "needs_review": 0, "rejected": 0}
    try:
        for cand in targets:
            stats["attempted"] += 1
            _match_candidate(db, cand, min_coverage)
            if cand["stock_status"] == "matched":
                stats["matched"] += 1
            elif cand["stock_status"] == "needs_review":
                stats["needs_review"] += 1
            else:
                stats["rejected"] += 1
    finally:
        db.close()

    _save_cache(args.cache_dir, cache)
    logger.info(
        "match: attempted=%d matched=%d needs_review=%d rejected=%d",
        stats["attempted"], stats["matched"], stats["needs_review"], stats["rejected"],
    )
    return 0


def _match_candidate(db: Session, cand: dict, min_coverage: float) -> None:
    """A line with no stated quantity at all ("Salt, to taste") can never
    become a RecipeIngredient (quantity_g is required) regardless of how
    well its name matches a Food — that's an inherent property of the
    source line, not a matching failure. Coverage and
    Recipe.unresolved_ingredients are about matching quality, so those
    quantity-less lines are tracked (still visible in cand["matches"] for
    review-file transparency) but excluded from both — otherwise every
    recipe with "salt and pepper to taste" would be needlessly penalised,
    and coverage would say nothing about actual match quality."""
    parsed_ingredients = [ParsedIngredient(**p) for p in cand["parsed_ingredients"]]
    match_rows: list[dict] = []
    resolutions: list[tuple[bool, float | None]] = []
    unresolved_lines: list[str] = []

    for parsed in parsed_ingredients:
        quantity_stated = parsed.normalised_quantity is not None
        match: MatchResult = match_ingredient(db, parsed.name)
        row: dict[str, Any] = {
            "raw_text": parsed.raw_text,
            "name": parsed.name,
            "optional": parsed.optional,
            "quantity_stated": quantity_stated,
            "method": match.method,
            "confidence": match.confidence,
            "candidates": [asdict(c) for c in match.candidates],
            "food_id": match.food.id if match.food else None,
            "food_name": match.food.name if match.food else None,
            "quantity_g": None,
            "conversion_confidence": None,
            "conversion_assumptions": None,
            "resolved": False,
        }

        grams = None
        if match.food is not None and quantity_stated:
            conversion = convert(parsed.normalised_quantity, parsed.unit, parsed.name)
            if conversion is not None:
                grams = conversion.grams
                row["quantity_g"] = grams
                row["conversion_confidence"] = conversion.confidence
                row["conversion_assumptions"] = conversion.assumptions

        row["resolved"] = match.food is not None and grams is not None
        if quantity_stated:
            if not row["resolved"]:
                unresolved_lines.append(parsed.raw_text)
            resolutions.append((row["resolved"], grams))
        match_rows.append(row)

    coverage = compute_coverage(resolutions)
    cand["matches"] = match_rows
    cand["match_coverage_lines"] = coverage.line_coverage
    cand["match_coverage_mass"] = coverage.mass_coverage
    cand["unresolved_ingredients"] = unresolved_lines

    reasons = []
    if not resolutions:
        reasons.append("no ingredient line has a stated quantity")
    elif coverage.line_coverage < min_coverage:
        reasons.append(f"ingredient-line match coverage {coverage.line_coverage:.0%} below the {min_coverage:.0%} threshold")
    if not cand.get("servings") or cand["servings"] <= 0:
        reasons.append("missing or non-positive serving count")
    total_mass = sum(g for _, g in resolutions if g is not None)
    if total_mass < 50:
        reasons.append(f"implausibly low total resolved ingredient mass ({total_mass:.0f}g)")

    if resolutions and not any(r[0] for r in resolutions):
        cand["stock_status"] = "rejected"
        cand["status_reason"] = "no ingredient could be matched to any food"
    elif reasons:
        cand["stock_status"] = "needs_review"
        cand["status_reason"] = "; ".join(reasons)
    else:
        cand["stock_status"] = "matched"
        cand["status_reason"] = None


# --- stage: analyse ----------------------------------------------------------

def cmd_analyse(args) -> int:
    simulation_count = getattr(args, "simulation_count", DEFAULT_SIMULATION_COUNT)
    random_seed = getattr(args, "random_seed", DEFAULT_RANDOM_SEED)

    cache = _load_cache(args.cache_dir)
    targets = _filtered_candidates(cache, args, ("matched", "needs_review"))

    # duplicate detection runs across every non-terminal candidate, not
    # just this run's --limit/--source/--collection-filtered targets, since
    # a duplicate pair can span two different filtered subsets
    all_active = [c for c in cache.values() if c["stock_status"] in ("matched", "needs_review")]
    duplicates = dedup.find_near_duplicates([(c["slug"], c["name"]) for c in all_active])
    by_slug: dict[str, list[str]] = {}
    for a, b, score in duplicates:
        by_slug.setdefault(a, []).append(f"{b} ({score:.0%} title similarity)")
        by_slug.setdefault(b, []).append(f"{a} ({score:.0%} title similarity)")

    db = SessionLocal()
    stats = {"attempted": 0, "analysed": 0, "failed": 0}
    try:
        for cand in targets:
            stats["attempted"] += 1
            cand["duplicate_candidates"] = by_slug.get(cand["slug"], [])
            try:
                _analyse_candidate(db, cand, simulation_count, random_seed)
                stats["analysed"] += 1
            except Exception:
                logger.exception("analysis failed for %s", cand["slug"])
                stats["failed"] += 1
    finally:
        db.close()

    _save_cache(args.cache_dir, cache)
    logger.info("analyse: attempted=%d analysed=%d failed=%d", stats["attempted"], stats["analysed"], stats["failed"])
    return 0


def _resolved_foods(db: Session, cand: dict) -> list[tuple[models.Food, float, bool, str | None, float | None]]:
    """Returns (food, quantity_g, optional, conversion_confidence,
    parsing_confidence) for every resolved match row."""
    parsed_by_raw = {p["raw_text"]: p for p in cand["parsed_ingredients"]}
    out = []
    food_ids = [row["food_id"] for row in cand["matches"] if row["resolved"]]
    foods_by_id = {f.id: f for f in db.query(models.Food).filter(models.Food.id.in_(food_ids)).all()}
    for row in cand["matches"]:
        if not row["resolved"]:
            continue
        food = foods_by_id.get(row["food_id"])
        if food is None:
            continue
        parsed = parsed_by_raw.get(row["raw_text"], {})
        out.append((food, row["quantity_g"], row["optional"], row["conversion_confidence"], parsed.get("parsing_confidence")))
    return out


def _analyse_candidate(db: Session, cand: dict, simulation_count: int, random_seed: int) -> None:
    from ..aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients

    resolved = _resolved_foods(db, cand)
    servings = cand["servings"] or 1.0
    food_ids = [f.id for f, *_ in resolved]
    nutrients_by_food_id: dict[int, list[models.FoodNutrient]] = {}
    for fn in db.query(models.FoodNutrient).filter(models.FoodNutrient.food_id.in_(food_ids)).all():
        nutrients_by_food_id.setdefault(fn.food_id, []).append(fn)

    items = [WeightedFood(f, qty) for f, qty, *_ in resolved]
    totals = aggregate_nutrients(items, nutrients_by_food_id, divide_by=servings)
    aggregate = aggregate_amino_acids(items)
    cand["nutrition_summary"] = {
        "energy_kcal_per_serving": totals.get("energy"),
        "protein_g_per_serving": (aggregate.total_protein_g / servings) if aggregate.total_protein_g > 0 else 0.0,
        "iron_mg_per_serving": totals.get("iron"),
        "calcium_mg_per_serving": totals.get("calcium"),
        "fibre_g_per_serving": totals.get("fiber_total"),
        "sodium_mg_per_serving": totals.get("sodium"),
    }

    foods = [f for f, *_ in resolved]
    computed_collections = compute_suitability_collections(foods, has_unresolved_ingredients=bool(cand["unresolved_ingredients"]))
    cand["computed_collections"] = computed_collections

    ingredient_inputs = [
        RobustnessIngredientInput(
            food=f, quantity_g=qty, optional=optional,
            bound_fraction=estimate_bound_fraction(conv_confidence, parsing_confidence),
        )
        for f, qty, optional, conv_confidence, parsing_confidence in resolved
    ]
    analysis: RobustnessAnalysis = run_robustness(
        ingredient_inputs, servings, nutrients_by_food_id,
        unmatched_mass_fraction=1.0 - (cand["match_coverage_mass"] or 1.0),
        simulation_count=simulation_count, random_seed=random_seed,
    )
    cand["robustness"] = {
        "model_version": analysis.model_version,
        "simulation_count": analysis.simulation_count,
        "random_seed": analysis.random_seed,
        "overall_rating": analysis.overall_rating,
        "overall_explanation": analysis.overall_explanation,
        "metrics": {key: asdict(m) for key, m in analysis.metrics.items()},
    }


# --- stage: review-export -----------------------------------------------

_CSV_FIELDS = [
    "slug", "name", "source", "source_name", "source_url", "collections", "servings",
    "stock_status", "match_coverage_lines", "match_coverage_mass", "unresolved_count",
    "overall_rating", "warnings", "duplicate_candidates", "proposed_publication_status",
]


def cmd_review_export(args) -> int:
    cache = _load_cache(args.cache_dir)
    exportable = [c for c in cache.values() if c["stock_status"] in ("matched", "needs_review", "rejected", "source_unavailable")]

    args.review_file.parent.mkdir(parents=True, exist_ok=True)
    with open(args.review_file, "w", encoding="utf-8") as f:
        json.dump(exportable, f, indent=2, sort_keys=True)

    csv_path = args.review_file.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for c in exportable:
            warnings = []
            if c["status_reason"]:
                warnings.append(c["status_reason"])
            if c["unresolved_ingredients"]:
                warnings.append(f"{len(c['unresolved_ingredients'])} unresolved ingredient line(s)")
            writer.writerow({
                "slug": c["slug"],
                "name": c["name"],
                "source": c["source"],
                "source_name": c["source_name"],
                "source_url": c["source_url"] or "",
                "collections": ",".join(c["collections"]),
                "servings": c["servings"],
                "stock_status": c["stock_status"],
                "match_coverage_lines": c["match_coverage_lines"],
                "match_coverage_mass": c["match_coverage_mass"],
                "unresolved_count": len(c["unresolved_ingredients"]),
                "overall_rating": (c["robustness"] or {}).get("overall_rating") if c["robustness"] else None,
                "warnings": "; ".join(warnings),
                "duplicate_candidates": "; ".join(c["duplicate_candidates"]),
                "proposed_publication_status": c["proposed_publication_status"],
            })

    logger.info("review-export: %d candidates written to %s (+ %s)", len(exportable), args.review_file, csv_path)
    return 0


# --- stage: import-approved -----------------------------------------------

def _ensure_system_user(db: Session) -> models.User:
    user = db.query(models.User).filter(models.User.is_system.is_(True)).one_or_none()
    if user is not None:
        return user
    user = models.User(
        email=SYSTEM_USER_EMAIL,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        is_system=True,
    )
    db.add(user)
    db.flush()
    return user


def _ensure_collections(db: Session, system_user: models.User) -> dict[str, models.Collection]:
    existing = {
        c.name: c
        for c in db.query(models.Collection).filter(models.Collection.user_id == system_user.id).all()
    }
    result = {}
    for spec in COLLECTIONS.values():
        collection = existing.get(spec.name)
        if collection is None:
            collection = models.Collection(user_id=system_user.id, name=spec.name, is_public=True)
            db.add(collection)
            db.flush()
        result[spec.key] = collection
    return result


def _load_review(review_file: Path) -> tuple[list[dict], dict[str, str]]:
    with open(review_file, encoding="utf-8") as f:
        rows = json.load(f)
    statuses: dict[str, str] = {}
    csv_path = review_file.with_suffix(".csv")
    if csv_path.exists():
        with open(csv_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                statuses[row["slug"]] = row["proposed_publication_status"]
    for row in rows:
        if row["slug"] in statuses:
            row["proposed_publication_status"] = statuses[row["slug"]]
    return rows, statuses


def cmd_import_approved(args) -> int:
    if not args.review_file.exists():
        logger.error("review file not found: %s (run review-export first)", args.review_file)
        return 1

    rows, _ = _load_review(args.review_file)
    approved = [r for r in rows if r["proposed_publication_status"] == "approved"]
    rejected = [r for r in rows if r["proposed_publication_status"] == "rejected"]

    invalid = [r["slug"] for r in approved if not r.get("matches") or r["robustness"] is None]
    if invalid:
        logger.error("refusing to import approved candidate(s) missing match/analysis data: %s", invalid)
        return 1

    cache = _load_cache(args.cache_dir)

    if getattr(args, "dry_run", False):
        logger.info("import-approved (dry-run): would import %d, mark %d rejected", len(approved), len(rejected))
        return 0

    db = SessionLocal()
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "rejected": 0}
    try:
        system_user = _ensure_system_user(db)
        collections_by_key = _ensure_collections(db, system_user)

        for row in rejected:
            if row["slug"] in cache:
                cache[row["slug"]]["stock_status"] = "rejected"
            stats["rejected"] += 1

        for row in approved:
            recipe_id = _import_one(db, row, system_user, collections_by_key)
            if row["slug"] in cache:
                cache[row["slug"]]["stock_status"] = "imported"
                cache[row["slug"]]["imported_recipe_id"] = recipe_id
            stats["inserted"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    _save_cache(args.cache_dir, cache)
    logger.info(
        "import-approved: inserted/updated=%d rejected=%d", stats["inserted"], stats["rejected"],
    )
    return 0


def _import_one(
    db: Session, row: dict, system_user: models.User, collections_by_key: dict[str, models.Collection]
) -> int:
    """A row only gets here because a maintainer marked it "approved" in
    the review file — that approval IS the human sign-off to write exactly
    this ingredient set, so this always overwrites. The "don't silently
    replace manual corrections" protection (prompt section 12) instead
    lives in cmd_refresh, which runs unattended against a live source with
    no human re-reviewing each recipe — see its docstring."""
    existing = db.query(models.Recipe).filter(models.Recipe.import_slug == row["slug"]).one_or_none()

    if existing is None:
        recipe = models.Recipe(
            user_id=system_user.id, name=row["name"], servings=row["servings"] or 1.0, is_public=True,
            import_slug=row["slug"],
        )
        db.add(recipe)
        db.flush()
    else:
        recipe = existing
        recipe.name = row["name"]
        recipe.servings = row["servings"] or recipe.servings
        recipe.is_public = True
        db.query(models.RecipeIngredientProvenance).filter(
            models.RecipeIngredientProvenance.recipe_ingredient_id.in_(
                db.query(models.RecipeIngredient.id).filter(models.RecipeIngredient.recipe_id == recipe.id)
            )
        ).delete(synchronize_session=False)
        db.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe.id).delete()

    recipe.source_url = row["source_url"]
    recipe.source_name = row["source_name"]
    recipe.source_licence = row.get("source_licence")
    recipe.retrieved_at = _parse_iso(row.get("retrieved_at"))
    recipe.parser_version = PARSER_VERSION
    # the source's own content fingerprint (from fetch) — what refresh()
    # compares fresh fetches against to detect source-side drift. Manual
    # (never-fetched) candidates have none.
    recipe.content_fingerprint = row.get("content_fingerprint")
    recipe.stock_status = "imported"
    recipe.match_coverage_lines = row["match_coverage_lines"]
    recipe.match_coverage_mass = row["match_coverage_mass"]
    recipe.unresolved_ingredients = row["unresolved_ingredients"]
    recipe.educational_note = row.get("educational_note")

    for m in row["matches"]:
        if not m["resolved"]:
            continue
        ingredient = models.RecipeIngredient(recipe_id=recipe.id, food_id=m["food_id"], quantity_g=m["quantity_g"])
        db.add(ingredient)
        db.flush()
        db.add(models.RecipeIngredientProvenance(
            recipe_ingredient_id=ingredient.id,
            raw_text=m["raw_text"],
            quantity_min=None, quantity_max=None, normalised_quantity=None, unit=None,
            prep_note=None, optional_flag=m["optional"], section=None,
            parsing_confidence=None,
            match_method=m["method"], match_confidence=m["confidence"],
            match_candidates=m["candidates"], manually_approved=False,
            conversion_assumptions=m["conversion_assumptions"],
        ))

    _sync_collections(db, recipe, row, collections_by_key)
    _upsert_robustness(db, recipe, row["robustness"])

    return recipe.id


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _sync_collections(db: Session, recipe: models.Recipe, row: dict, collections_by_key: dict[str, models.Collection]) -> None:
    wanted: dict[str, tuple[str, float | None, str | None]] = {}
    for key in row["collections"]:
        if key in collections_by_key:
            wanted[key] = ("manual", None, "curated in the seed manifest")
    for key in row.get("computed_collections", []):
        if key in collections_by_key:
            wanted[key] = ("computed", 1.0, "every ingredient evaluated suitable for this dietary pattern")

    existing_links = {
        cr.collection_id: cr
        for cr in db.query(models.CollectionRecipe).filter(models.CollectionRecipe.recipe_id == recipe.id).all()
    }
    wanted_collection_ids = {collections_by_key[k].id for k in wanted}

    for collection_id, link in existing_links.items():
        if collection_id not in wanted_collection_ids:
            db.delete(link)

    for key, (source, confidence, reason) in wanted.items():
        collection = collections_by_key[key]
        link = existing_links.get(collection.id)
        if link is None:
            db.add(models.CollectionRecipe(
                collection_id=collection.id, recipe_id=recipe.id,
                assignment_source=source, assignment_confidence=confidence,
                assignment_reason=reason, approval_status="approved",
            ))
        else:
            link.assignment_source = source
            link.assignment_confidence = confidence
            link.assignment_reason = reason


def _upsert_robustness(db: Session, recipe: models.Recipe, robustness: dict | None) -> None:
    if robustness is None:
        return
    existing = db.query(models.RobustnessResult).filter(models.RobustnessResult.recipe_id == recipe.id).one_or_none()
    kwargs = {
        "model_version": robustness["model_version"],
        "computed_at": datetime.now(timezone.utc),
        "simulation_count": robustness["simulation_count"],
        "random_seed": robustness["random_seed"],
        "metrics": robustness["metrics"],
        "overall_rating": robustness["overall_rating"],
        "overall_explanation": robustness["overall_explanation"],
    }
    if existing is None:
        db.add(models.RobustnessResult(recipe_id=recipe.id, **kwargs))
    else:
        for k, v in kwargs.items():
            setattr(existing, k, v)


# --- stage: refresh -----------------------------------------------------

def cmd_refresh(args) -> int:
    """Re-fetches already-imported fetch-sourced recipes and detects source
    drift, comparing the fresh content_fingerprint against the one stored
    at last import (both computed the same way, by the adapter — see
    sources/base.py's RawRecipe). Manual-sourced recipes have nothing to
    re-fetch — their content only ever changes via a manual_recipes.json
    edit, picked up by rerunning discover/fetch/parse/match/analyse/
    import-approved for that slug like any other update.

    refresh NEVER writes to RecipeIngredient itself — that's the whole
    "avoid replacing manual corrections silently" guarantee (prompt
    section 12): a source-side change only ever (a) refreshes that
    candidate's cached raw content back to stock_status "discovered" so
    the normal parse/match/analyse pipeline can reprocess it, and (b)
    flags the *already-imported* Recipe row as needs_review, without
    touching a single one of its existing RecipeIngredient rows. Only a
    subsequent, explicitly human-approved import-approved run ever
    replaces them."""
    entries_by_slug = {e.slug: e for e in load_manifest() if e.source == "fetch"}
    adapters = build_adapters({})
    cache = _load_cache(args.cache_dir)

    db = SessionLocal()
    stats = {"checked": 0, "unchanged": 0, "drifted": 0, "unavailable": 0}
    try:
        imported = (
            db.query(models.Recipe)
            .filter(models.Recipe.import_slug.in_(list(entries_by_slug)), models.Recipe.stock_status == "imported")
            .all()
        )
        for recipe in imported:
            entry = entries_by_slug[recipe.import_slug]
            adapter = adapters.get(entry.source_name)
            if adapter is None:
                continue
            stats["checked"] += 1
            try:
                raw = adapter.fetch(entry, args.cache_dir, force_refresh=getattr(args, "force_refresh", False))
            except SourceUnavailable as e:
                recipe.stock_status = "source_unavailable"
                logger.warning("refresh: %s unavailable: %s", entry.slug, e)
                stats["unavailable"] += 1
                continue

            if raw.content_fingerprint == recipe.content_fingerprint:
                stats["unchanged"] += 1
                continue

            recipe.stock_status = "needs_review"
            logger.info(
                "refresh: %s (recipe %d) changed at the source — existing ingredients left untouched; "
                "flagged needs_review, cache refreshed for a fresh parse/match/analyse/review pass",
                entry.slug, recipe.id,
            )
            if entry.slug in cache:
                cache[entry.slug]["raw_ingredient_lines"] = raw.ingredient_lines
                cache[entry.slug]["servings"] = raw.servings
                cache[entry.slug]["content_fingerprint"] = raw.content_fingerprint
                cache[entry.slug]["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                cache[entry.slug]["stock_status"] = "discovered"
            stats["drifted"] += 1

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    _save_cache(args.cache_dir, cache)
    logger.info(
        "refresh: checked=%d unchanged=%d drifted=%d unavailable=%d",
        stats["checked"], stats["unchanged"], stats["drifted"], stats["unavailable"],
    )
    return 0


# --- stage: report -----------------------------------------------------

def cmd_report(args) -> int:
    cache = _load_cache(args.cache_dir)
    by_status: dict[str, int] = {}
    for c in cache.values():
        by_status[c["stock_status"]] = by_status.get(c["stock_status"], 0) + 1

    print("Stock recipe pipeline report")
    print("=============================")
    print(f"Total candidates known: {len(cache)}")
    for status in ("discovered", "parsed", "matched", "needs_review", "approved", "rejected", "imported", "source_unavailable"):
        print(f"  {status:20s} {by_status.get(status, 0)}")

    manifest_total = len(load_manifest())
    print(f"\nManifest target size: {manifest_total}")
    print(f"Not yet discovered: {manifest_total - len(cache)}")

    unresolved_total = sum(len(c["unresolved_ingredients"]) for c in cache.values())
    print(f"\nTotal unresolved ingredient lines across all candidates: {unresolved_total}")

    duplicates = {c["slug"] for c in cache.values() if c["duplicate_candidates"]}
    print(f"Candidates with a flagged near-duplicate: {len(duplicates)}")

    return 0
