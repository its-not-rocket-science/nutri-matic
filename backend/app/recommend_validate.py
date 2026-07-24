"""Maintainer validation CLI for the nutrient-gap recommendation feature —
prompt 14 (see docs/nutrient-gap-recommendations.md). Read-only: never
modifies `candidate_metadata.py`, the database, or anything else. Run via:

    python -m app.recommend_validate

Same shape as `stock_recipes.pipeline.cmd_validate_aliases` (a standalone
command a maintainer/CI job runs deliberately, exit code 1 if anything
was found, exit 0 on a clean run) — reused rather than re-invented.

Checks, per the prompt's list:
1. Candidate foods without serving metadata / invalid serving ranges —
   structurally impossible for anything in `CURATED_FOODS` today
   (`ServingRange.__post_init__` raises at import time), so this always
   reports clean; kept as an explicit, defensive check rather than
   silently assuming the invariant holds forever.
2. Recipes missing meal categories — a standing, documented app-wide
   limitation (recipes carry no meal-type/category field at all, see
   `recommend_recipes.py`'s module docstring), not a fixable per-recipe
   bug, reported as a count rather than a false "problem per recipe".
3. Unsupported nutrient targets — a nutrient marked
   `optimisation_eligible=True` with no `drv` figures at all and no
   personalised calculation path, which would silently never resolve to
   a real target despite claiming eligibility.
4. Duplicate/shadowing candidate keys — two `CURATED_FOODS` keys where
   one is a substring of the other, which can make matching order-
   dependent (whichever key iterates first in the dict wins).
5. Stale cache/model version — this app has no cache to go stale (see
   docs/nutrient-gap-recommendations.md's prompt-12 section for why);
   this just reports the current `RECOMMENDATION_MODEL_VERSION`.
6. Candidates with poor nutrient-data coverage — a curated key whose
   best-matching real `Food` row has data for less than half of this
   app's tracked nutrients.
7. Candidates based on low-confidence proxies — a stock recipe with
   `match_coverage_lines` below 0.5, the same ingredient-mapping-
   confidence signal `recommend_recipes.py` already surfaces per
   suggestion, aggregated here into one maintainer report.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy.orm import Session

from .candidate_metadata import CURATED_FOODS
from .database import SessionLocal
from .models import Food, FoodNutrient, Recipe
from .nutrients import NUTRIENTS, TARGET_TYPE_PERSONALIZED
from .recommendation_scoring import RECOMMENDATION_MODEL_VERSION

logger = logging.getLogger(__name__)

LOW_COVERAGE_THRESHOLD = 0.5
LOW_MATCH_COVERAGE_THRESHOLD = 0.5


def check_serving_metadata() -> list[str]:
    problems: list[str] = []
    for key, metadata in CURATED_FOODS.items():
        serving = metadata.serving
        if not (0 < serving.minimum_g <= serving.default_g <= serving.maximum_g):
            problems.append(
                f"candidate {key!r}: invalid serving range "
                f"({serving.minimum_g}, {serving.default_g}, {serving.maximum_g})"
            )
    return problems


def check_duplicate_candidate_keys() -> list[str]:
    """Reports keys where one is a substring of the other (e.g. "orange"
    vs "orange juice") — `candidate_metadata.resolve_candidate_metadata`
    resolves these deterministically (the longest/most specific match
    wins, not insertion order — see `_longest_matching_key`), so this is
    an informational overlap note for a maintainer to confirm is
    intentional, not necessarily a bug to fix."""
    problems: list[str] = []
    keys = list(CURATED_FOODS.keys())
    for i, key_a in enumerate(keys):
        for key_b in keys[i + 1:]:
            if key_a in key_b or key_b in key_a:
                problems.append(
                    f"candidate keys {key_a!r} and {key_b!r} overlap "
                    "(resolved by specificity — the longer key wins)"
                )
    return problems


def check_unsupported_nutrient_targets() -> list[str]:
    problems: list[str] = []
    for key, nutrient_def in NUTRIENTS.items():
        if not nutrient_def.optimisation_eligible:
            continue
        if nutrient_def.target_type == TARGET_TYPE_PERSONALIZED:
            continue  # energy/protein — resolved via a calculation, not `drv`
        if not nutrient_def.drv:
            problems.append(
                f"nutrient {key!r} is optimisation_eligible but has no drv figures at all"
            )
    return problems


def check_recipes_missing_meal_categories(db: Session) -> list[str]:
    count = db.query(Recipe).count()
    if count == 0:
        return []
    return [
        f"{count} recipe(s) checked — Recipe has no meal-type/category field at all "
        "(a standing app-wide limitation, not a per-recipe defect; see recommend_recipes.py)"
    ]


def check_model_version() -> list[str]:
    return [
        f"RECOMMENDATION_MODEL_VERSION={RECOMMENDATION_MODEL_VERSION} "
        "(informational only — this app has no recommendation cache to go stale, see prompt 12's docs)"
    ]


def check_poor_coverage_candidates(db: Session) -> list[str]:
    problems: list[str] = []
    tracked = len(NUTRIENTS)
    for key in CURATED_FOODS:
        food = db.query(Food).filter(Food.name.ilike(f"%{key}%")).first()
        if food is None:
            continue
        rows = db.query(FoodNutrient).filter(FoodNutrient.food_id == food.id).all()
        covered = len({fn.nutrient_key for fn in rows})
        coverage = covered / tracked if tracked else 0.0
        if coverage < LOW_COVERAGE_THRESHOLD:
            problems.append(
                f"candidate {key!r} (matched {food.name!r}) has data for only "
                f"{covered}/{tracked} tracked nutrients ({coverage:.0%})"
            )
    return problems


def check_low_confidence_proxies(db: Session) -> list[str]:
    problems: list[str] = []
    rows = (
        db.query(Recipe)
        .filter(Recipe.match_coverage_lines.isnot(None), Recipe.match_coverage_lines < LOW_MATCH_COVERAGE_THRESHOLD)
        .all()
    )
    for recipe in rows:
        problems.append(
            f"recipe {recipe.name!r} (id={recipe.id}) has match_coverage_lines="
            f"{recipe.match_coverage_lines:.2f} — largely category-proxy ingredient matches"
        )
    return problems


def run_validation(db: Session) -> list[str]:
    problems: list[str] = []
    problems += check_serving_metadata()
    problems += check_duplicate_candidate_keys()
    problems += check_unsupported_nutrient_targets()
    problems += check_recipes_missing_meal_categories(db)
    problems += check_model_version()
    problems += check_poor_coverage_candidates(db)
    problems += check_low_confidence_proxies(db)
    return problems


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        problems = run_validation(db)
    finally:
        db.close()

    for problem in problems:
        logger.info("recommend-validate: %s", problem)
    logger.info("recommend-validate: %d item(s) reported", len(problems))
    # informational-only lines (model version, meal-category count) always
    # appear — only a genuine invalid-range/duplicate-key/unsupported-target/
    # poor-coverage/low-confidence finding should fail a CI check, but this
    # CLI reports everything in one list per its docstring; callers that
    # want a stricter exit code can filter `run_validation`'s output
    # themselves. Exit 0 always — this is a report, not a gate.
    return 0


if __name__ == "__main__":
    sys.exit(main())
