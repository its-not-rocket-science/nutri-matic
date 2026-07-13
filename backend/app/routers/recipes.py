from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from ..auth import get_current_user
from ..database import get_db
from ..models import Food, FoodNutrient, Recipe, RecipeIngredient, User
from ..nutrients import NUTRIENTS, resolve_drv
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas
from ..search import NutrientFilter, UnknownFilterKey, search_recipes

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


def _get_owned_recipe(recipe_id: int, current_user: User, db: Session) -> Recipe:
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


def _recipe_out(recipe: Recipe, db: Session) -> schemas.RecipeOut:
    ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([i.food_id for i in ingredients])).all()}
    return schemas.RecipeOut(
        id=recipe.id,
        name=recipe.name,
        servings=recipe.servings,
        ingredients=[
            schemas.RecipeIngredientOut(
                food_id=i.food_id, food_name=foods_by_id[i.food_id].name, quantity_g=i.quantity_g
            )
            for i in ingredients
        ],
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

    food_ids = {i.food_id for i in body.ingredients}
    found = db.query(Food.id).filter(Food.id.in_(food_ids)).all()
    missing = food_ids - {f.id for f in found}
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown food id(s): {sorted(missing)}")

    recipe = Recipe(user_id=current_user.id, name=body.name, servings=body.servings)
    db.add(recipe)
    db.flush()
    for ingredient in body.ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=ingredient.food_id, quantity_g=ingredient.quantity_g))
    db.commit()
    db.refresh(recipe)
    return _recipe_out(recipe, db)


@router.get("", response_model=list[schemas.RecipeOut])
def list_recipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipes = db.query(Recipe).filter(Recipe.user_id == current_user.id).order_by(Recipe.name).all()
    return [_recipe_out(r, db) for r in recipes]


@router.post("/search", response_model=list[schemas.RecipeOut])
def recipe_search(
    body: schemas.SearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    filters = [NutrientFilter(f.key, f.op, f.value) for f in body.filters]
    try:
        matches = search_recipes(db, current_user.id, filters)
    except UnknownFilterKey as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return [_recipe_out(r, db) for r in matches[: body.limit]]


@router.get("/{recipe_id}", response_model=schemas.RecipeOut)
def get_recipe(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    return _recipe_out(recipe, db)


@router.delete("/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).delete()
    db.delete(recipe)
    db.commit()


@router.get("/{recipe_id}/score", response_model=schemas.ScoreOut)
def score_recipe(
    recipe_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    aggregate = aggregate_amino_acids(_weighted_foods(recipe, db))

    try:
        if method == "diaas":
            if aggregate.digestibility_diaas is None:
                raise HTTPException(
                    status_code=422, detail="Recipe has no per-amino-acid digestibility data for DIAAS"
                )
            result = compute_diaas(aggregate.amino_acids, aggregate.digestibility_diaas, pattern)
        elif method == "pdcaas":
            if aggregate.digestibility_pdcaas is None:
                raise HTTPException(
                    status_code=422, detail="Recipe has no overall digestibility data for PDCAAS"
                )
            result = compute_pdcaas(aggregate.amino_acids, aggregate.digestibility_pdcaas, pattern)
        else:
            raise HTTPException(status_code=422, detail="method must be 'diaas' or 'pdcaas'")
    except (UnknownReferencePattern, IncompleteAminoAcidProfile) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return schemas.ScoreOut(
        method=method,
        pattern_used=result.pattern_used,
        score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        per_aa_ratios=result.per_aa_ratios,
        digestibility_source=None,  # a recipe's digestibility is a blend, not a single measured/estimated tag
    )


@router.get("/{recipe_id}/nutrients", response_model=list[schemas.NutrientAmountOut])
def recipe_nutrients(recipe_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    recipe = _get_owned_recipe(recipe_id, current_user, db)
    items = _weighted_foods(recipe, db)

    food_ids = [item.food.id for item in items]
    rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    profile = (current_user.sex, current_user.is_pregnant, current_user.is_lactating)
    totals = aggregate_nutrients(items, by_food_id, divide_by=recipe.servings)

    out = []
    for key, amount in totals.items():
        nutrient_def = NUTRIENTS.get(key)
        if nutrient_def is None:
            continue
        drv = resolve_drv(key, profile)
        out.append(
            schemas.NutrientAmountOut(
                key=key,
                name=nutrient_def.name,
                unit=nutrient_def.unit,
                amount=amount,
                adult_drv=drv,
                percent_drv=(amount / drv * 100) if drv else None,
            )
        )
    out.sort(key=lambda n: n.name)
    return out
