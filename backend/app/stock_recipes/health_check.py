"""Read-only health-check subsystem for the curated stock recipe library —
prompt section 5.

`run_health_check` re-fetches every already-imported, fetch-sourced
recipe's source page (through the same SourceAdapter every other stage
uses, so the same robots.txt/rate-limit/caching rules apply) and reports:

    * dead_url            — the source page is now unreachable/404/etc
    * redirect             — the source URL now redirects somewhere else
    * content_changed      — the source's extracted content fingerprint
                             no longer matches what was last imported
    * missing_licence      — no source licence is recorded at all
    * ingredients_changed  — the source's ingredient lines differ from
                             what's stored in this recipe's provenance
    * nutrition_changed    — re-resolving the fresh ingredient lines
                             produces a materially different per-serving
                             energy/protein figure
    * rematch_recommended  — the signals above suggest a maintainer should
                             rerun match/analyse and re-review before
                             republishing

Unlike `refresh` (pipeline.cmd_refresh), which is part of the normal
reprocessing pipeline and does flag Recipe.stock_status when it detects
drift, this module NEVER writes to the database, the candidate cache, or
any Recipe row — see prompt section 5: "generate review reports only,
never silently modify public recipes." A maintainer reads the report
(write_health_report) and decides what to do by hand, the same way they
review review-export's output before import-approved.

Manual-sourced recipes have no source page to check at all and are never
examined here; only fetch-sourced, currently-imported recipes are.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from ..aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from .food_matching import CoverageResult, compute_coverage, match_ingredient
from .ingredient_parser import parse_ingredient_lines
from .manifest import load_manifest
from .sources import SourceUnavailable, build_adapters
from .unit_conversion import convert

logger = logging.getLogger(__name__)

# a per-serving energy/protein change bigger than this fraction, found when
# re-resolving a recipe's freshly-fetched ingredient lines, is reported as
# "nutrition_changed" — a judgement call (not a scientific threshold) about
# what's worth a maintainer's attention rather than routine source noise.
NUTRITION_CHANGE_THRESHOLD = 0.15
# a fresh line-coverage drop bigger than this many percentage points (on
# top of the recipe's own last-recorded coverage) contributes to a
# "rematch_recommended" flag.
COVERAGE_DROP_THRESHOLD = 0.05

_CSV_FIELDS = ["recipe_id", "slug", "name", "issue_type", "detail"]


@dataclass
class HealthIssue:
    recipe_id: int
    slug: str
    name: str
    issue_type: str
    detail: str


def _current_nutrition(db: Session, recipe: models.Recipe) -> dict[str, float | None]:
    """The recipe's nutrition as it stands today, from its existing
    (already-resolved, already-converted-to-grams) RecipeIngredient rows —
    the "before" side of a nutrition_changed comparison."""
    ingredients = db.query(models.RecipeIngredient).filter(models.RecipeIngredient.recipe_id == recipe.id).all()
    foods_by_id = {
        f.id: f for f in db.query(models.Food).filter(models.Food.id.in_([i.food_id for i in ingredients])).all()
    }
    items = [WeightedFood(foods_by_id[i.food_id], i.quantity_g) for i in ingredients if i.food_id in foods_by_id]
    return _nutrition_summary(db, items, recipe.servings or 1.0)


def _resolve_ingredients(db: Session, ingredient_lines: list[str]) -> tuple[list[WeightedFood], CoverageResult]:
    parsed = parse_ingredient_lines(ingredient_lines)
    items: list[WeightedFood] = []
    resolutions: list[tuple[bool, float | None]] = []
    for p in parsed:
        quantity_stated = p.normalised_quantity is not None
        grams = None
        match = match_ingredient(db, p.name)
        if match.food is not None and quantity_stated:
            conversion = convert(p.normalised_quantity, p.unit, p.name)
            if conversion is not None:
                grams = conversion.grams
                items.append(WeightedFood(match.food, grams))
        if quantity_stated:
            resolutions.append((grams is not None, grams))
    return items, compute_coverage(resolutions)


def _nutrition_summary(db: Session, items: list[WeightedFood], servings: float) -> dict[str, float | None]:
    food_ids = [wf.food.id for wf in items]
    nutrients_by_food_id: dict[int, list[models.FoodNutrient]] = {}
    for fn in db.query(models.FoodNutrient).filter(models.FoodNutrient.food_id.in_(food_ids)).all():
        nutrients_by_food_id.setdefault(fn.food_id, []).append(fn)
    totals = aggregate_nutrients(items, nutrients_by_food_id, divide_by=servings or 1.0)
    aggregate = aggregate_amino_acids(items)
    return {
        "energy_kcal_per_serving": totals.get("energy"),
        "protein_g_per_serving": (aggregate.total_protein_g / servings) if servings else None,
    }


def _stored_ingredient_lines(db: Session, recipe_id: int) -> list[str]:
    rows = (
        db.query(models.RecipeIngredientProvenance.raw_text)
        .join(
            models.RecipeIngredient,
            models.RecipeIngredient.id == models.RecipeIngredientProvenance.recipe_ingredient_id,
        )
        .filter(models.RecipeIngredient.recipe_id == recipe_id)
        .all()
    )
    return [r[0] for r in rows]


def run_health_check(db: Session, cache_dir: Path, *, force_refresh: bool = True) -> list[HealthIssue]:
    entries_by_slug = {e.slug: e for e in load_manifest() if e.source == "fetch"}
    adapters = build_adapters({})
    issues: list[HealthIssue] = []

    recipes = (
        db.query(models.Recipe)
        .filter(models.Recipe.import_slug.in_(list(entries_by_slug)), models.Recipe.stock_status == "imported")
        .all()
    )

    for recipe in recipes:
        entry = entries_by_slug[recipe.import_slug]
        slug, name = recipe.import_slug, recipe.name

        if not recipe.source_licence:
            issues.append(HealthIssue(
                recipe.id, slug, name, "missing_licence",
                "No source licence is recorded for this imported recipe.",
            ))

        adapter = adapters.get(entry.source_name)
        if adapter is None:
            continue

        try:
            raw = adapter.fetch(entry, cache_dir, force_refresh=force_refresh)
        except SourceUnavailable as e:
            issues.append(HealthIssue(recipe.id, slug, name, "dead_url", str(e)))
            continue

        if raw.resolved_url and entry.source_url and raw.resolved_url != entry.source_url:
            issues.append(HealthIssue(
                recipe.id, slug, name, "redirect",
                f"{entry.source_url} now redirects to {raw.resolved_url}",
            ))

        content_changed = raw.content_fingerprint != recipe.content_fingerprint
        if content_changed:
            issues.append(HealthIssue(
                recipe.id, slug, name, "content_changed",
                "Source content fingerprint no longer matches the last import.",
            ))

        stored_lines = sorted(_stored_ingredient_lines(db, recipe.id))
        fresh_lines = sorted(raw.ingredient_lines)
        ingredients_changed = stored_lines != fresh_lines
        if ingredients_changed:
            added = len(set(fresh_lines) - set(stored_lines))
            removed = len(set(stored_lines) - set(fresh_lines))
            issues.append(HealthIssue(
                recipe.id, slug, name, "ingredients_changed",
                f"{added} ingredient line(s) added, {removed} removed since last import.",
            ))

        if not (content_changed or ingredients_changed):
            continue

        items, coverage = _resolve_ingredients(db, raw.ingredient_lines)
        fresh = _nutrition_summary(db, items, raw.servings or recipe.servings or 1.0)
        current = _current_nutrition(db, recipe)
        for key in ("energy_kcal_per_serving", "protein_g_per_serving"):
            before, after = current.get(key), fresh.get(key)
            if before and after and abs(after - before) / before > NUTRITION_CHANGE_THRESHOLD:
                issues.append(HealthIssue(
                    recipe.id, slug, name, "nutrition_changed",
                    f"{key} changed from {before:.1f} to {after:.1f} ({(after - before) / before:+.0%}).",
                ))

        recorded_coverage = recipe.match_coverage_lines if recipe.match_coverage_lines is not None else 1.0
        if coverage.line_coverage < recorded_coverage - COVERAGE_DROP_THRESHOLD:
            issues.append(HealthIssue(
                recipe.id, slug, name, "rematch_recommended",
                f"Fresh ingredient match coverage ({coverage.line_coverage:.0%}) is lower than the recipe's "
                f"last recorded coverage ({recorded_coverage:.0%}).",
            ))
        elif ingredients_changed:
            issues.append(HealthIssue(
                recipe.id, slug, name, "rematch_recommended",
                "Source ingredient list changed since last import — rerun match/analyse and review before republishing.",
            ))

    return issues


def write_health_report(path: Path, issues: list[HealthIssue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(i) for i in issues], f, indent=2, sort_keys=True)

    csv_path = path.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for issue in issues:
            writer.writerow(asdict(issue))
