"""Canonical recipe-access resolvers — the one place recipe visibility
is decided, reused by both `routers/recipes.py` and
`routers/recommendations.py` (see hardening prompt 1,
docs/nutrient-gap-recommendations.md).

Recipe access is a separate boundary from profile ownership: a request
can be fully authenticated and scoped to a profile the caller legitimately
owns while still asking about a *recipe* that profile has no right to see
(another user's private recipe, guessed by ID). Every recipe-scoped
endpoint — viewing, scoring, nutrients, robustness, and now
recommendations — must resolve that boundary through `get_visible_recipe`
(read-only access: owner, explicitly shared-with, or public/system-owned
stock) or `get_owned_recipe` (mutating access: owner only), never by
calling `db.get(Recipe, recipe_id)` directly and skipping the check.

Both raise a plain 404 ("Recipe not found") for anything inaccessible —
never 403 — so a caller probing recipe IDs can't distinguish "doesn't
exist" from "exists but isn't yours", matching this app's existing
anti-enumeration convention (`routers/recipes.py` already did this for
every one of its own endpoints; this module just gives that logic one
home instead of re-implementing it per router).
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Recipe, RecipeShare, User


def is_shared_with(recipe_id: int, user_id: int, db: Session) -> bool:
    return (
        db.query(RecipeShare)
        .filter(RecipeShare.recipe_id == recipe_id, RecipeShare.shared_with_user_id == user_id)
        .first()
        is not None
    )


def get_owned_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    """For mutating operations (delete, share management, apply-a-
    substitution) — owner only."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


def get_visible_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    """For read-only operations (view, score, nutrients, copy, and now
    recommendation analysis) — owner, anyone the recipe has been shared
    with, or anyone at all if it's public (covers system-owned/public
    stock recipes too, since those are always created with
    `is_public=True`, not a separate flag)."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if (
        recipe.user_id != current_user.id
        and not recipe.is_public
        and not is_shared_with(recipe_id, current_user.id, db)
    ):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe
