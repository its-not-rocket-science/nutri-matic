"""Applies a profile's dietary constraints (Phase 3; per-individual since
the household-profiles feature) to food/recipe results. Only hard
exclusions are enforced here — a food matching an "avoid"-severity
constraint is left in place (that's the whole distinction between the two
severities; see routers/profiles.py and dietary_tags.py). Anonymous callers
and search/discovery endpoints without an explicit profile_id (profile is
None) never filter anything, since there's no profile to check against —
the latter defaults to the caller's owner profile (see
auth.get_optional_owned_profile), not whichever dependent profile is
active in the frontend, a documented limitation until search/discovery
endpoints take an explicit profile_id too.

Filtering (this module's original purpose) only ever removes "excluded"
items — it deliberately doesn't distinguish "ok" from "avoid" from
"unknown" for the results that remain, because dropping is a yes/no
decision. Search/discovery *display*, however, needs that distinction: a
result search silently shows "avoid" and "unknown" foods identically to
verified-safe ones, which is exactly the "unknown treated as safe" failure
dietary_tags.py's own module docstring warns against. `food_dietary_status`/
`foods_dietary_status`/`recipe_dietary_status` below compute that status for
display, without changing what filter_excluded_foods/filter_excluded_recipes
already (correctly) drop.
"""

from sqlalchemy.orm import Session

from .dietary_tags import Suitability, evaluate_food
from .models import DietaryConstraint, Food, Profile, Recipe, RecipeIngredient

# worst-first, for picking a recipe's overall status across its ingredients
_STATUS_SEVERITY = {"ok": 0, "unknown": 1, "avoid": 2, "excluded": 3}


def load_constraint_tags(db: Session, profile: Profile | None) -> list[tuple[str, str]]:
    if profile is None:
        return []
    rows = (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.profile_id == profile.id, DietaryConstraint.tag.isnot(None))
        .all()
    )
    return [(row.tag, row.severity) for row in rows if row.severity]


def is_hard_excluded(food: Food, dietary_pattern: str | None, constraint_tags: list[tuple[str, str]]) -> bool:
    if not dietary_pattern and not constraint_tags:
        return False
    return evaluate_food(food.name, food.data_type, dietary_pattern, constraint_tags).status == "excluded"


def filter_excluded_foods(foods: list[Food], db: Session, profile: Profile | None) -> list[Food]:
    """Drops any food that's a hard exclusion for `profile`. A no-op for
    anonymous callers or a profile with no dietary_pattern/constraints set."""
    if profile is None:
        return foods
    constraint_tags = load_constraint_tags(db, profile)
    if not profile.dietary_pattern and not constraint_tags:
        return foods
    return [f for f in foods if not is_hard_excluded(f, profile.dietary_pattern, constraint_tags)]


def food_dietary_status(food: Food, db: Session, profile: Profile | None) -> Suitability | None:
    """For display, not filtering — None (render no badge) for anonymous
    callers or a profile with no dietary_pattern/constraints set, same
    early-return convention as filter_excluded_foods."""
    if profile is None:
        return None
    constraint_tags = load_constraint_tags(db, profile)
    if not profile.dietary_pattern and not constraint_tags:
        return None
    return evaluate_food(food.name, food.data_type, profile.dietary_pattern, constraint_tags)


def foods_dietary_status(foods: list[Food], db: Session, profile: Profile | None) -> dict[int, Suitability]:
    """Batch form of food_dietary_status — one constraint-tags query for the
    whole list rather than one per food. Only "avoid"/"unknown" entries are
    included (never "ok", never "excluded" — those are dropped by
    filter_excluded_foods before display, not badged)."""
    if profile is None or not foods:
        return {}
    constraint_tags = load_constraint_tags(db, profile)
    if not profile.dietary_pattern and not constraint_tags:
        return {}
    result: dict[int, Suitability] = {}
    for food in foods:
        suitability = evaluate_food(food.name, food.data_type, profile.dietary_pattern, constraint_tags)
        if suitability.status in ("avoid", "unknown"):
            result[food.id] = suitability
    return result


def _recipe_ingredients_map(recipes: list[Recipe], db: Session) -> dict[int, list[Food]]:
    recipe_ids = [r.id for r in recipes]
    ingredient_rows = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id.in_(recipe_ids)).all()
    food_ids = {row.food_id for row in ingredient_rows}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}

    ingredients_by_recipe: dict[int, list[Food]] = {}
    for row in ingredient_rows:
        food = foods_by_id.get(row.food_id)
        if food is not None:
            ingredients_by_recipe.setdefault(row.recipe_id, []).append(food)
    return ingredients_by_recipe


def filter_excluded_recipes(recipes: list[Recipe], db: Session, profile: Profile | None) -> list[Recipe]:
    """Drops any recipe with at least one hard-excluded ingredient for
    `profile` — used for recipe *search/discovery* (a suggestion context),
    not a user's own plain recipe listing (see routers/recipes.py for why
    that distinction matters: hiding a recipe you already made from your
    own list, just because you set a new allergy afterwards, would be more
    confusing than helpful — this is for finding something new)."""
    if profile is None or not recipes:
        return recipes
    constraint_tags = load_constraint_tags(db, profile)
    if not profile.dietary_pattern and not constraint_tags:
        return recipes

    ingredients_by_recipe = _recipe_ingredients_map(recipes, db)

    def recipe_ok(recipe: Recipe) -> bool:
        ingredients = ingredients_by_recipe.get(recipe.id, [])
        return not any(is_hard_excluded(f, profile.dietary_pattern, constraint_tags) for f in ingredients)

    return [r for r in recipes if recipe_ok(r)]


def recipes_dietary_status(recipes: list[Recipe], db: Session, profile: Profile | None) -> dict[int, Suitability]:
    """Batch, display-only counterpart to filter_excluded_recipes — the
    worst status across each recipe's ingredients (excluded ones are
    assumed already dropped by filter_excluded_recipes; this is for
    flagging "avoid"/"unknown" among the recipes that remain). Only
    "avoid"/"unknown" entries are included, same convention as
    foods_dietary_status."""
    if profile is None or not recipes:
        return {}
    constraint_tags = load_constraint_tags(db, profile)
    if not profile.dietary_pattern and not constraint_tags:
        return {}

    ingredients_by_recipe = _recipe_ingredients_map(recipes, db)
    result: dict[int, Suitability] = {}
    for recipe in recipes:
        ingredients = ingredients_by_recipe.get(recipe.id, [])
        worst: Suitability | None = None
        for food in ingredients:
            suitability = evaluate_food(food.name, food.data_type, profile.dietary_pattern, constraint_tags)
            if worst is None or _STATUS_SEVERITY[suitability.status] > _STATUS_SEVERITY[worst.status]:
                worst = suitability
        if worst is not None and worst.status in ("avoid", "unknown"):
            result[recipe.id] = worst
    return result
