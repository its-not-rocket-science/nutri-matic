from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import WeightedFood, aggregate_nutrients, compute_protein_quality_with_coverage
from ..auth import get_current_user
from ..database import get_db
from ..dietary_filter import filter_excluded_recipes, recipes_dietary_status
from ..energy_goal import calculate_energy_target
from ..models import (
    Food,
    FoodNutrient,
    Recipe,
    RecipeComment,
    RecipeIngredient,
    RecipeRating,
    RecipeShare,
    RecipeTag,
    RobustnessResult,
    User,
)
from ..methodology import SCORING_METHODOLOGY_VERSION
from ..nutrients import NUTRIENTS, resolve_drv
from ..protein_absorption import compute_absorbed_protein_with_coverage
from ..protein_requirement import calculate_protein_target_g
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import UnknownReferencePattern
from ..search import NutrientFilter, UnknownFilterKey, search_recipes

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


def _is_shared_with(recipe_id: int, user_id: int, db: Session) -> bool:
    return (
        db.query(RecipeShare)
        .filter(RecipeShare.recipe_id == recipe_id, RecipeShare.shared_with_user_id == user_id)
        .first()
        is not None
    )


def _get_owned_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    """For mutating operations (delete, share management) — owner only."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


def _get_visible_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    """For read-only operations (view, score, nutrients, copy) — owner,
    anyone the recipe has been shared with, or anyone at all if it's public."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if (
        recipe.user_id != current_user.id
        and not recipe.is_public
        and not _is_shared_with(recipe_id, current_user.id, db)
    ):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


def _rating_summary(recipe_id: int, user_id: int, db: Session) -> schemas.RecipeRatingSummary:
    ratings = [r.rating for r in db.query(RecipeRating).filter(RecipeRating.recipe_id == recipe_id).all()]
    mine = db.query(RecipeRating).filter(
        RecipeRating.recipe_id == recipe_id, RecipeRating.user_id == user_id
    ).one_or_none()
    return schemas.RecipeRatingSummary(
        average=(sum(ratings) / len(ratings)) if ratings else None,
        count=len(ratings),
        my_rating=mine.rating if mine else None,
    )


def _validate_source_url(source_url: str | None) -> None:
    if source_url is not None and not (source_url.startswith("http://") or source_url.startswith("https://")):
        raise HTTPException(status_code=422, detail="source_url must start with http:// or https://")


def _recipe_out(recipe: Recipe, db: Session, current_user: User) -> schemas.RecipeOut:
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([i.food_id for i in ingredients])).all()}
    owner = db.get(User, recipe.user_id)
    ratings = [r.rating for r in db.query(RecipeRating).filter(RecipeRating.recipe_id == recipe.id).all()]
    tags = [t.tag for t in db.query(RecipeTag).filter(RecipeTag.recipe_id == recipe.id).order_by(RecipeTag.tag).all()]
    return schemas.RecipeOut(
        id=recipe.id,
        name=recipe.name,
        servings=recipe.servings,
        ingredients=[
            schemas.RecipeIngredientOut(
                id=i.id, food_id=i.food_id, food_name=foods_by_id[i.food_id].name, quantity_g=i.quantity_g
            )
            for i in ingredients
        ],
        owner_email=owner.email,
        is_owner=recipe.user_id == current_user.id,
        is_public=recipe.is_public,
        average_rating=(sum(ratings) / len(ratings)) if ratings else None,
        rating_count=len(ratings),
        tags=tags,
        source_url=recipe.source_url,
        method=recipe.method,
        is_stock=owner.is_system,
        source_name=recipe.source_name,
        match_coverage_lines=recipe.match_coverage_lines,
        match_coverage_mass=recipe.match_coverage_mass,
        unresolved_ingredients=recipe.unresolved_ingredients or [],
    )


def _weighted_foods(recipe: Recipe, db: Session) -> list[WeightedFood]:
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([i.food_id for i in ingredients])).all()}
    return [WeightedFood(foods_by_id[i.food_id], i.quantity_g) for i in ingredients]


@router.post("", response_model=schemas.RecipeOut, status_code=201)
def create_recipe(
    body: schemas.RecipeCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if not body.ingredients:
        raise HTTPException(status_code=422, detail="A recipe needs at least one ingredient")
    if body.servings <= 0:
        raise HTTPException(status_code=422, detail="servings must be positive")
    _validate_source_url(body.source_url)

    food_ids = {i.food_id for i in body.ingredients}
    found = db.query(Food.id).filter(Food.id.in_(food_ids)).all()
    missing = food_ids - {f.id for f in found}
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown food id(s): {sorted(missing)}")

    recipe = Recipe(
        user_id=current_user.id,
        name=body.name,
        servings=body.servings,
        source_url=body.source_url,
        method=body.method,
    )
    db.add(recipe)
    db.flush()
    for ingredient in body.ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=ingredient.food_id, quantity_g=ingredient.quantity_g))
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db, current_user)


@router.get("", response_model=list[schemas.RecipeOut])
def list_recipes(
    tag: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    query = db.query(Recipe).filter(Recipe.user_id == current_user.id)
    if tag is not None:
        query = query.filter(
            Recipe.id.in_(db.query(RecipeTag.recipe_id).filter(RecipeTag.tag == tag))
        )
    recipes = query.order_by(Recipe.name).all()
    return [_recipe_out(r, db, current_user) for r in recipes]


@router.get("/tags", response_model=list[str])
def list_my_tags(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Distinct tags across the current user's own recipes, for autocomplete
    when tagging any recipe."""
    rows = (
        db.query(RecipeTag.tag)
        .join(Recipe, Recipe.id == RecipeTag.recipe_id)
        .filter(Recipe.user_id == current_user.id)
        .distinct()
        .order_by(RecipeTag.tag)
        .all()
    )
    return [r[0] for r in rows]


@router.get("/shared-with-me", response_model=list[schemas.RecipeOut])
def list_shared_with_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    shares = db.query(RecipeShare).filter(RecipeShare.shared_with_user_id == current_user.id).all()
    recipes = [db.get(Recipe, s.recipe_id) for s in shares]
    recipes = [r for r in recipes if r is not None]
    recipes.sort(key=lambda r: r.name)
    return [_recipe_out(r, db, current_user) for r in recipes]


@router.get("/public", response_model=list[schemas.RecipeOut])
def list_public_recipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stock recipes — visible to everyone, not just their owner."""
    recipes = db.query(Recipe).filter(Recipe.is_public.is_(True)).order_by(Recipe.name).all()
    return [_recipe_out(r, db, current_user) for r in recipes]


@router.post("/search", response_model=list[schemas.RecipeOut])
def recipe_search(
    body: schemas.SearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    filters = [NutrientFilter(f.key, f.op, f.value) for f in body.filters]
    try:
        matches = search_recipes(db, current_user.id, filters)
    except UnknownFilterKey as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    matches = filter_excluded_recipes(matches, db, current_user)
    matches = matches[: body.limit]
    status_by_id = recipes_dietary_status(matches, db, current_user)
    out = []
    for r in matches:
        recipe_out = _recipe_out(r, db, current_user)
        suitability = status_by_id.get(r.id)
        recipe_out.dietary_status = (
            schemas.DietaryStatusOut(status=suitability.status, confidence=suitability.confidence, reasons=suitability.reasons)
            if suitability is not None
            else None
        )
        out.append(recipe_out)
    return out


@router.get("/{recipe_id}", response_model=schemas.RecipeOut)
def get_recipe(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_visible_recipe(recipe_id, current_user, db)
    return _recipe_out(recipe, db, current_user)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete()
    db.delete(recipe)
    db.commit()


@router.patch("/{recipe_id}", response_model=schemas.RecipeOut)
def update_recipe(
    recipe_id: int,
    body: schemas.RecipeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=422, detail="Name can't be empty")
        recipe.name = body.name
    if body.servings is not None:
        if body.servings <= 0:
            raise HTTPException(status_code=422, detail="servings must be positive")
        recipe.servings = body.servings
    # source_url/method are optional metadata (unlike name/servings, which
    # are required and so can't meaningfully be "cleared") — distinguish
    # "omitted" (leave alone) from "explicitly null" (clear it) via
    # model_fields_set, rather than treating both as "leave alone"
    if "source_url" in body.model_fields_set:
        if body.source_url is not None:
            _validate_source_url(body.source_url)
        recipe.source_url = body.source_url
    if "method" in body.model_fields_set:
        recipe.method = body.method
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db, current_user)


@router.post("/{recipe_id}/ingredients", response_model=schemas.RecipeOut, status_code=201)
def add_ingredient(
    recipe_id: int,
    body: schemas.RecipeIngredientAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    if body.quantity_g <= 0:
        raise HTTPException(status_code=422, detail="quantity_g must be positive")
    food = db.get(Food, body.food_id)
    if food is None:
        raise HTTPException(status_code=422, detail=f"Unknown food id: {body.food_id}")
    exists = db.query(RecipeIngredient).filter(
        RecipeIngredient.recipe_id == recipe.id, RecipeIngredient.food_id == body.food_id
    ).one_or_none()
    if exists is not None:
        raise HTTPException(status_code=409, detail="This food is already an ingredient in this recipe")
    db.add(RecipeIngredient(recipe_id=recipe.id, food_id=body.food_id, quantity_g=body.quantity_g))
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db, current_user)


@router.patch("/{recipe_id}/ingredients/{ingredient_id}", response_model=schemas.RecipeOut)
def update_ingredient(
    recipe_id: int,
    ingredient_id: int,
    body: schemas.RecipeIngredientUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    ingredient = db.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe.id:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    if body.quantity_g <= 0:
        raise HTTPException(status_code=422, detail="quantity_g must be positive")
    ingredient.quantity_g = body.quantity_g
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db, current_user)


@router.delete("/{recipe_id}/ingredients/{ingredient_id}", response_model=schemas.RecipeOut)
def remove_ingredient(
    recipe_id: int,
    ingredient_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    ingredient = db.get(RecipeIngredient, ingredient_id)
    if ingredient is None or ingredient.recipe_id != recipe.id:
        raise HTTPException(status_code=404, detail="Ingredient not found")
    remaining = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).count()
    if remaining <= 1:
        raise HTTPException(status_code=422, detail="A recipe needs at least one ingredient")
    db.delete(ingredient)
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db, current_user)


@router.get("/{recipe_id}/score", response_model=schemas.ScoreOut)
def score_recipe(
    recipe_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if method not in ("diaas", "pdcaas"):
        raise HTTPException(status_code=422, detail="method must be 'diaas' or 'pdcaas'")

    recipe = _get_visible_recipe(recipe_id, current_user, db)
    try:
        quality = compute_protein_quality_with_coverage(_weighted_foods(recipe, db), method, pattern)
    except UnknownReferencePattern as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if quality.score is None:
        detail = (
            f"Recipe has insufficient ingredient coverage to calculate {method.upper()} "
            f"(only {quality.coverage_fraction:.0%} of protein-contributing ingredients have "
            "amino acid data)"
            if quality.total_protein_g > 0
            else f"Recipe has no protein-contributing ingredients with amino acid data for {method.upper()}"
        )
        raise HTTPException(status_code=422, detail=detail)

    return schemas.ScoreOut(
        method=method,
        pattern_used=quality.score.pattern_used,
        score=quality.score.score,
        limiting_amino_acid=quality.score.limiting_amino_acid,
        per_aa_ratios=quality.score.per_aa_ratios,
        digestibility_source=quality.digestibility_source,
        methodology_version=SCORING_METHODOLOGY_VERSION,
        coverage_fraction=quality.coverage_fraction,
        is_partial=quality.coverage_fraction < 1.0,
        excluded_ingredients=[
            schemas.ExcludedIngredientOut(**f) for f in quality.excluded_foods
        ],
    )


@router.get("/{recipe_id}/nutrients", response_model=list[schemas.NutrientAmountOut])
def recipe_nutrients(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_visible_recipe(recipe_id, current_user, db)
    items = _weighted_foods(recipe, db)

    food_ids = [item.food.id for item in items]
    rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    profile = (current_user.sex, current_user.is_pregnant, current_user.is_lactating)
    totals = aggregate_nutrients(items, by_food_id, divide_by=recipe.servings)
    protein_target = calculate_protein_target_g(current_user)
    energy_result = calculate_energy_target(current_user)
    energy_target, energy_goal_adjusted = energy_result if energy_result is not None else (None, False)

    out = []
    for key, amount in totals.items():
        nutrient_def = NUTRIENTS.get(key)
        if nutrient_def is None:
            continue
        # energy's/protein's targets are personalized calculations, not a
        # sex/life-stage table lookup — resolve_drv() correctly returns None
        # for them (see nutrients.py), so they're handled separately here,
        # same as diary.py's day/trend endpoints
        if key == "energy":
            out.append(
                schemas.NutrientAmountOut.build(
                    key, nutrient_def, amount, energy_target,
                    drv_source=(
                        "Personalized target: Mifflin-St Jeor BMR x activity level, minus a weight-loss-goal "
                        "calorie deficit (see energy_goal.py) — see the note on this page for what that means"
                        if energy_goal_adjusted
                        else "Personalized target: Mifflin-St Jeor BMR x activity level (see energy.py)"
                    ),
                    drv_confidence="personalized_calculation",
                    goal_adjusted=energy_goal_adjusted,
                )
            )
            continue
        if key == "protein":
            out.append(
                schemas.NutrientAmountOut.build(
                    key, nutrient_def, amount, protein_target,
                    drv_source="Personalized target: bodyweight x activity-level protein factor (see protein_requirement.py)",
                    drv_confidence="personalized_calculation",
                )
            )
            continue
        drv = resolve_drv(key, profile)
        out.append(schemas.NutrientAmountOut.build(key, nutrient_def, amount, drv))
    out.sort(key=lambda n: n.name)
    return out


@router.get("/{recipe_id}/absorbed-protein", response_model=schemas.AbsorbedProteinOut | None)
def recipe_absorbed_protein(
    recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Per-serving counterpart to the diary day summary's absorbed_protein —
    same DIAAS/PDCAAS-weighted total, scaled to one serving of this recipe
    instead of a whole day's entries. Returns None if the recipe has no
    protein-contributing ingredients."""
    recipe = _get_visible_recipe(recipe_id, current_user, db)
    items = _weighted_foods(recipe, db)

    absorbed = compute_absorbed_protein_with_coverage(items)
    if absorbed is None:
        return None

    target_g = calculate_protein_target_g(current_user)
    total_protein_g = absorbed.total_protein_g / recipe.servings
    diaas_absorbed_g = absorbed.diaas_absorbed_g / recipe.servings if absorbed.diaas_absorbed_g is not None else None
    pdcaas_absorbed_g = (
        absorbed.pdcaas_absorbed_g / recipe.servings if absorbed.pdcaas_absorbed_g is not None else None
    )

    return schemas.AbsorbedProteinOut(
        total_protein_g=total_protein_g,
        diaas_absorbed_g=diaas_absorbed_g,
        pdcaas_absorbed_g=pdcaas_absorbed_g,
        target_g=target_g,
        diaas_percent_drv=(diaas_absorbed_g / target_g * 100) if diaas_absorbed_g is not None and target_g else None,
        pdcaas_percent_drv=(
            pdcaas_absorbed_g / target_g * 100 if pdcaas_absorbed_g is not None and target_g else None
        ),
        diaas_coverage_fraction=absorbed.diaas_coverage_fraction,
        pdcaas_coverage_fraction=absorbed.pdcaas_coverage_fraction,
    )


@router.get("/{recipe_id}/robustness", response_model=schemas.RobustnessOut | None)
def recipe_robustness(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A stock recipe's nutritional-robustness analysis — see
    stock_recipes/robustness.py. None for a recipe that's never been
    analysed (e.g. any ordinary user-created recipe)."""
    _get_visible_recipe(recipe_id, current_user, db)
    result = db.query(RobustnessResult).filter(RobustnessResult.recipe_id == recipe_id).one_or_none()
    if result is None:
        return None
    return schemas.RobustnessOut(
        model_version=result.model_version,
        computed_at=result.computed_at,
        simulation_count=result.simulation_count,
        random_seed=result.random_seed,
        metrics={key: schemas.RobustnessMetricOut(**value) for key, value in result.metrics.items()},
        overall_rating=result.overall_rating,
        overall_explanation=result.overall_explanation,
    )


@router.get("/{recipe_id}/shares", response_model=list[schemas.RecipeShareOut])
def list_shares(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    shares = db.query(RecipeShare).filter(RecipeShare.recipe_id == recipe.id).all()
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([s.shared_with_user_id for s in shares])).all()}
    return [
        schemas.RecipeShareOut(id=s.id, email=users_by_id[s.shared_with_user_id].email, created_at=s.created_at)
        for s in shares
    ]


@router.post("/{recipe_id}/shares", response_model=schemas.RecipeShareOut, status_code=201)
def create_share(
    recipe_id: int,
    body: schemas.RecipeShareCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)

    target = db.query(User).filter(User.email == body.email).one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail=f"No user with email: {body.email}")
    if target.id == current_user.id:
        raise HTTPException(status_code=422, detail="Can't share a recipe with yourself")
    if _is_shared_with(recipe.id, target.id, db):
        raise HTTPException(status_code=409, detail=f"Already shared with {body.email}")

    share = RecipeShare(recipe_id=recipe.id, shared_with_user_id=target.id)
    db.add(share)
    db.commit()
    db.refresh(share)
    return schemas.RecipeShareOut(id=share.id, email=target.email, created_at=share.created_at)


@router.delete("/{recipe_id}/shares/{share_id}", status_code=204)
def delete_share(
    recipe_id: int, share_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    share = db.get(RecipeShare, share_id)
    if share is None or share.recipe_id != recipe.id:
        raise HTTPException(status_code=404, detail="Share not found")
    db.delete(share)
    db.commit()


@router.post("/{recipe_id}/copy", response_model=schemas.RecipeOut, status_code=201)
def copy_recipe(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Clones a recipe (view-visible to the caller — their own, or shared
    with them) into a brand new recipe owned by the caller, which they can
    then edit freely. The original is untouched."""
    original = _get_visible_recipe(recipe_id, current_user, db)
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == original.id).all()

    copy = Recipe(user_id=current_user.id, name=f"{original.name} (copy)", servings=original.servings)
    db.add(copy)
    db.flush()
    for ingredient in ingredients:
        db.add(RecipeIngredient(recipe_id=copy.id, food_id=ingredient.food_id, quantity_g=ingredient.quantity_g))
    db.commit()
    db.refresh(copy)
    return _recipe_out(copy, db, current_user)


@router.get("/{recipe_id}/ratings", response_model=schemas.RecipeRatingSummary)
def get_ratings(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_visible_recipe(recipe_id, current_user, db)
    return _rating_summary(recipe_id, current_user.id, db)


@router.post("/{recipe_id}/ratings", response_model=schemas.RecipeRatingSummary)
def rate_recipe(
    recipe_id: int,
    body: schemas.RecipeRatingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upsert — rating again just replaces your previous rating."""
    _get_visible_recipe(recipe_id, current_user, db)
    existing = db.query(RecipeRating).filter(
        RecipeRating.recipe_id == recipe_id, RecipeRating.user_id == current_user.id
    ).one_or_none()
    if existing:
        existing.rating = body.rating
    else:
        db.add(RecipeRating(recipe_id=recipe_id, user_id=current_user.id, rating=body.rating))
    db.commit()
    return _rating_summary(recipe_id, current_user.id, db)


@router.delete("/{recipe_id}/ratings", response_model=schemas.RecipeRatingSummary)
def delete_rating(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_visible_recipe(recipe_id, current_user, db)
    existing = db.query(RecipeRating).filter(
        RecipeRating.recipe_id == recipe_id, RecipeRating.user_id == current_user.id
    ).one_or_none()
    if existing:
        db.delete(existing)
        db.commit()
    return _rating_summary(recipe_id, current_user.id, db)


@router.get("/{recipe_id}/comments", response_model=list[schemas.RecipeCommentOut])
def list_comments(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _get_visible_recipe(recipe_id, current_user, db)
    comments = (
        db.query(RecipeComment).filter(RecipeComment.recipe_id == recipe_id).order_by(RecipeComment.created_at).all()
    )
    users_by_id = {u.id: u for u in db.query(User).filter(User.id.in_([c.user_id for c in comments])).all()}
    return [
        schemas.RecipeCommentOut(
            id=c.id,
            user_email=users_by_id[c.user_id].email,
            body=c.body,
            created_at=c.created_at,
            is_own=c.user_id == current_user.id,
        )
        for c in comments
    ]


@router.post("/{recipe_id}/comments", response_model=schemas.RecipeCommentOut, status_code=201)
def create_comment(
    recipe_id: int,
    body: schemas.RecipeCommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.body.strip():
        raise HTTPException(status_code=422, detail="Comment can't be empty")
    _get_visible_recipe(recipe_id, current_user, db)
    comment = RecipeComment(recipe_id=recipe_id, user_id=current_user.id, body=body.body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return schemas.RecipeCommentOut(
        id=comment.id, user_email=current_user.email, body=comment.body, created_at=comment.created_at, is_own=True
    )


@router.delete("/{recipe_id}/comments/{comment_id}", status_code=204)
def delete_comment(
    recipe_id: int, comment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    recipe = _get_visible_recipe(recipe_id, current_user, db)
    comment = db.get(RecipeComment, comment_id)
    if comment is None or comment.recipe_id != recipe.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    # comment author or the recipe owner (moderation) may delete
    if comment.user_id != current_user.id and recipe.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to delete this comment")
    db.delete(comment)
    db.commit()


@router.post("/{recipe_id}/tags", response_model=schemas.RecipeOut)
def add_tag(
    recipe_id: int, body: schemas.TagAdd, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    tag = body.tag.strip().lower()
    if not tag:
        raise HTTPException(status_code=422, detail="Tag can't be empty")
    exists = db.query(RecipeTag).filter(RecipeTag.recipe_id == recipe.id, RecipeTag.tag == tag).one_or_none()
    if exists is None:
        db.add(RecipeTag(recipe_id=recipe.id, tag=tag))
        db.commit()
    return _recipe_out(recipe, db, current_user)


@router.delete("/{recipe_id}/tags/{tag}", response_model=schemas.RecipeOut)
def remove_tag(
    recipe_id: int, tag: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    db.query(RecipeTag).filter(RecipeTag.recipe_id == recipe.id, RecipeTag.tag == tag).delete()
    db.commit()
    return _recipe_out(recipe, db, current_user)
