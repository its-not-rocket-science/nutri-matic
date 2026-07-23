"""Read-only health-check subsystem for the curated stock recipe library —
prompt sections 5/10.

`run_health_check` re-checks every already-imported stock recipe and
reports, where applicable:

    * dead_url               — the source page is now unreachable/404/etc
    * redirect                — the source URL now redirects somewhere else
    * canonical_url_changed   — the manifest's source_url has been edited
                                since this recipe was last imported
    * content_changed         — the source's extracted content fingerprint
                                no longer matches what was last imported
    * missing_licence         — no source licence is recorded at all
    * licence_changed         — the source's licence text itself changed
    * ingredients_changed     — the source's ingredient lines differ from
                                what's stored in this recipe's provenance
    * nutrition_changed       — re-resolving the fresh ingredient lines
                                produces a materially different per-serving
                                energy/protein figure
    * rematch_recommended     — the signals above suggest a maintainer
                                should rerun match/analyse and re-review
                                before republishing
    * preferred_target_missing — an ingredient's alias/reviewed mapping had
                                a preferred fdc_id/food_id that no longer
                                resolved (see food_matching.
                                validate_reviewed_mappings for the
                                registry-level version of this same check)
    * used_fallback_resolution — an ingredient resolved via the fallback
                                description search rather than its
                                preferred target
    * low_confidence_proxy    — an ingredient resolved through a
                                low-confidence alias/reviewed match
    * stale_robustness        — the recipe's latest robustness analysis
                                predates the current model version

The URL/licence/content/ingredient/nutrition checks above only apply to
fetch-sourced recipes (a manual recipe has no source page to re-check);
the mapping-quality checks (preferred_target_missing/used_fallback_
resolution/low_confidence_proxy/stale_robustness) run against every
imported stock recipe regardless of source, since alias/proxy matching and
robustness analysis apply equally to both.

Unlike `refresh` (pipeline.cmd_refresh), which is part of the normal
reprocessing pipeline and does flag Recipe.stock_status when it detects
drift, this module NEVER writes to the database, the candidate cache, or
any Recipe row — see prompt section 5: "generate review reports only,
never silently modify public recipes." A maintainer reads the report
(write_health_report) and decides what to do by hand, the same way they
review review-export's output before import-approved.
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
from .robustness import ROBUSTNESS_MODEL_VERSION
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
# an alias/manual_review match below this confidence is surfaced as
# "low_confidence_proxy" — matches the frontend's own "moderate confidence"
# cutoff (see recipes/[id]/+page.svelte's confidenceWords), so what a
# maintainer sees here lines up with what an end user would see too.
LOW_CONFIDENCE_THRESHOLD = 0.75

_CSV_FIELDS = ["recipe_id", "slug", "name", "issue_type", "severity", "detail", "recommended_action"]

# severity/recommended-action defaults per issue_type — informational only
# (this is metadata about the report, not a decision the app ever acts on
# automatically; see the module docstring's "generate review reports only").
_SEVERITY: dict[str, str] = {
    "dead_url": "critical",
    "redirect": "warning",
    "canonical_url_changed": "warning",
    "content_changed": "warning",
    "missing_licence": "warning",
    "licence_changed": "warning",
    "ingredients_changed": "warning",
    "nutrition_changed": "critical",
    "rematch_recommended": "warning",
    "preferred_target_missing": "warning",
    "used_fallback_resolution": "info",
    "low_confidence_proxy": "info",
    "stale_robustness": "info",
}
_RECOMMENDED_ACTION: dict[str, str] = {
    "dead_url": "Update or remove the manifest source_url — the page can no longer be fetched.",
    "redirect": "Update the manifest source_url to the new location.",
    "canonical_url_changed": "Rerun discover/fetch/parse/match/analyse/import-approved to pick up the manifest's new source_url.",
    "content_changed": "Rerun match/analyse and review before republishing.",
    "missing_licence": "Confirm the source's licence and record it, or remove the recipe if reuse isn't permitted.",
    "licence_changed": "Re-confirm the recipe is still permitted to be republished under the new licence text.",
    "ingredients_changed": "Rerun match/analyse and review before republishing.",
    "nutrition_changed": "Review the recomputed nutrition before republishing — do not import automatically.",
    "rematch_recommended": "Rerun match/analyse and review before republishing.",
    "preferred_target_missing": "Re-review this ingredient's alias mapping — its preferred target no longer resolves.",
    "used_fallback_resolution": "Consider re-pinning this alias to a fresh stable id — its preferred target was unavailable.",
    "low_confidence_proxy": "No action required — a coarse approximation is already documented in its rationale.",
    "stale_robustness": "Rerun `analyse` to refresh this recipe's robustness rating under the current model version.",
}


@dataclass
class HealthIssue:
    recipe_id: int
    slug: str
    name: str
    issue_type: str
    detail: str
    severity: str = "info"  # "info" | "warning" | "critical"
    recommended_action: str = "Review manually."


def _issue(recipe: models.Recipe, slug: str, name: str, issue_type: str, detail: str) -> HealthIssue:
    return HealthIssue(
        recipe_id=recipe.id, slug=slug, name=name, issue_type=issue_type, detail=detail,
        severity=_SEVERITY.get(issue_type, "info"),
        recommended_action=_RECOMMENDED_ACTION.get(issue_type, "Review manually."),
    )


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


def _mapping_quality_issues(db: Session, recipe: models.Recipe, slug: str, name: str) -> list[HealthIssue]:
    """Per-ingredient alias/proxy provenance checks — apply to every
    imported stock recipe regardless of source (manual or fetch), since
    alias/reviewed-substitution matching applies equally to both."""
    issues: list[HealthIssue] = []
    provenance_rows = (
        db.query(models.RecipeIngredientProvenance)
        .join(models.RecipeIngredient, models.RecipeIngredient.id == models.RecipeIngredientProvenance.recipe_ingredient_id)
        .filter(models.RecipeIngredient.recipe_id == recipe.id)
        .all()
    )
    for row in provenance_rows:
        if row.match_method not in ("alias", "manual_review"):
            continue
        if row.match_validation_warning:
            issue_type = "preferred_target_missing" if row.match_used_fallback else "used_fallback_resolution"
            issues.append(_issue(
                recipe, slug, name, issue_type,
                f"{row.raw_text!r}: {row.match_validation_warning}",
            ))
        elif row.match_used_fallback:
            issues.append(_issue(
                recipe, slug, name, "used_fallback_resolution",
                f"{row.raw_text!r} resolved via fallback description search instead of its preferred target.",
            ))
        if row.match_confidence is not None and row.match_confidence < LOW_CONFIDENCE_THRESHOLD:
            issues.append(_issue(
                recipe, slug, name, "low_confidence_proxy",
                f"{row.raw_text!r} resolved via a {row.match_relationship or 'low-confidence'} match "
                f"({row.match_confidence:.0%} confidence)"
                + (f": {row.match_rationale}" if row.match_rationale else "."),
            ))
    return issues


def _stale_robustness_issue(db: Session, recipe: models.Recipe, slug: str, name: str) -> HealthIssue | None:
    latest = (
        db.query(models.RobustnessResult)
        .filter(models.RobustnessResult.recipe_id == recipe.id, models.RobustnessResult.is_latest.is_(True))
        .one_or_none()
    )
    if latest is None:
        return None
    if latest.model_version == ROBUSTNESS_MODEL_VERSION:
        return None
    return _issue(
        recipe, slug, name, "stale_robustness",
        f"Latest robustness analysis used model version {latest.model_version!r}; "
        f"current model version is {ROBUSTNESS_MODEL_VERSION!r}.",
    )


def run_health_check(db: Session, cache_dir: Path, *, force_refresh: bool = True) -> list[HealthIssue]:
    entries_by_slug = {e.slug: e for e in load_manifest() if e.source == "fetch"}
    adapters = build_adapters({})
    issues: list[HealthIssue] = []

    all_recipes = db.query(models.Recipe).filter(models.Recipe.stock_status == "imported").all()

    for recipe in all_recipes:
        slug, name = recipe.import_slug, recipe.name
        issues.extend(_mapping_quality_issues(db, recipe, slug, name))
        stale = _stale_robustness_issue(db, recipe, slug, name)
        if stale is not None:
            issues.append(stale)

        entry = entries_by_slug.get(recipe.import_slug)
        if entry is None:
            continue  # manual-sourced recipe — no source page to re-check

        if not recipe.source_licence:
            issues.append(_issue(
                recipe, slug, name, "missing_licence",
                "No source licence is recorded for this imported recipe.",
            ))

        if entry.source_url and recipe.source_url and entry.source_url != recipe.source_url:
            issues.append(_issue(
                recipe, slug, name, "canonical_url_changed",
                f"Manifest source_url is now {entry.source_url!r}; this recipe was imported from {recipe.source_url!r}.",
            ))

        adapter = adapters.get(entry.source_name)
        if adapter is None:
            continue

        try:
            raw = adapter.fetch(entry, cache_dir, force_refresh=force_refresh)
        except SourceUnavailable as e:
            issues.append(_issue(recipe, slug, name, "dead_url", str(e)))
            continue

        if raw.resolved_url and entry.source_url and raw.resolved_url != entry.source_url:
            issues.append(_issue(
                recipe, slug, name, "redirect",
                f"{entry.source_url} now redirects to {raw.resolved_url}",
            ))

        if raw.source_licence and recipe.source_licence and raw.source_licence != recipe.source_licence:
            issues.append(_issue(
                recipe, slug, name, "licence_changed",
                f"Source licence text changed from {recipe.source_licence!r} to {raw.source_licence!r}.",
            ))

        content_changed = raw.content_fingerprint != recipe.content_fingerprint
        if content_changed:
            issues.append(_issue(
                recipe, slug, name, "content_changed",
                "Source content fingerprint no longer matches the last import.",
            ))

        stored_lines = sorted(_stored_ingredient_lines(db, recipe.id))
        fresh_lines = sorted(raw.ingredient_lines)
        ingredients_changed = stored_lines != fresh_lines
        if ingredients_changed:
            added = len(set(fresh_lines) - set(stored_lines))
            removed = len(set(stored_lines) - set(fresh_lines))
            issues.append(_issue(
                recipe, slug, name, "ingredients_changed",
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
                issues.append(_issue(
                    recipe, slug, name, "nutrition_changed",
                    f"{key} changed from {before:.1f} to {after:.1f} ({(after - before) / before:+.0%}).",
                ))

        recorded_coverage = recipe.match_coverage_lines if recipe.match_coverage_lines is not None else 1.0
        if coverage.line_coverage < recorded_coverage - COVERAGE_DROP_THRESHOLD:
            issues.append(_issue(
                recipe, slug, name, "rematch_recommended",
                f"Fresh ingredient match coverage ({coverage.line_coverage:.0%}) is lower than the recipe's "
                f"last recorded coverage ({recorded_coverage:.0%}).",
            ))
        elif ingredients_changed:
            issues.append(_issue(
                recipe, slug, name, "rematch_recommended",
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
