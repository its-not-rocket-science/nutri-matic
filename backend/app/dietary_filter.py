"""Applies a signed-in user's dietary constraints (Phase 3) to food/recipe
results. Only hard exclusions are enforced here — a food matching an
"avoid"-severity constraint is left in place (that's the whole distinction
between the two severities; see profile.py and dietary_tags.py). Anonymous
callers (current_user is None) never filter anything, since there's no
profile to check against.
"""

from sqlalchemy.orm import Session

from .dietary_tags import evaluate_food
from .models import DietaryConstraint, Food, Recipe, RecipeIngredient, User


def load_constraint_tags(db: Session, user: User | None) -> list[tuple[str, str]]:
    if user is None:
        return []
    rows = (
        db.query(DietaryConstraint)
        .filter(DietaryConstraint.user_id == user.id, DietaryConstraint.tag.isnot(None))
        .all()
    )
    return [(row.tag, row.severity) for row in rows if row.severity]


def is_hard_excluded(food: Food, dietary_pattern: str | None, constraint_tags: list[tuple[str, str]]) -> bool:
    if not dietary_pattern and not constraint_tags:
        return False
    return evaluate_food(food.name, food.data_type, dietary_pattern, constraint_tags).status == "excluded"


def filter_excluded_foods(foods: list[Food], db: Session, user: User | None) -> list[Food]:
    """Drops any food that's a hard exclusion for `user`. A no-op for
    anonymous callers or a user with no dietary_pattern/constraints set."""
    if user is None:
        return foods
    constraint_tags = load_constraint_tags(db, user)
    if not user.dietary_pattern and not constraint_tags:
        return foods
    return [f for f in foods if not is_hard_excluded(f, user.dietary_pattern, constraint_tags)]


def filter_excluded_recipes(recipes: list[Recipe], db: Session, user: User | None) -> list[Recipe]:
    """Drops any recipe with at least one hard-excluded ingredient for
    `user` — used for recipe *search/discovery* (a suggestion context), not
    a user's own plain recipe listing (see routers/recipes.py for why that
    distinction matters: hiding a recipe you already made from your own
    list, just because you set a new allergy afterwards, would be more
    confusing than helpful — this is for finding something new)."""
    if user is None or not recipes:
        return recipes
    constraint_tags = load_constraint_tags(db, user)
    if not user.dietary_pattern and not constraint_tags:
        return recipes

    recipe_ids = [r.id for r in recipes]
    ingredient_rows = (
        db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id.in_(recipe_ids)).all()
    )
    food_ids = {row.food_id for row in ingredient_rows}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}

    ingredients_by_recipe: dict[int, list[Food]] = {}
    for row in ingredient_rows:
        food = foods_by_id.get(row.food_id)
        if food is not None:
            ingredients_by_recipe.setdefault(row.recipe_id, []).append(food)

    def recipe_ok(recipe: Recipe) -> bool:
        ingredients = ingredients_by_recipe.get(recipe.id, [])
        return not any(is_hard_excluded(f, user.dietary_pattern, constraint_tags) for f in ingredients)

    return [r for r in recipes if recipe_ok(r)]
