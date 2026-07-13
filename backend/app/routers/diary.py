from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import WeightedFood, aggregate_nutrients, scale_recipe_ingredients
from ..auth import get_current_user
from ..database import get_db
from ..models import DiaryEntry, Food, FoodNutrient, Recipe, RecipeIngredient, User
from ..nutrients import NUTRIENTS, resolve_drv

router = APIRouter(prefix="/api/diary", tags=["diary"])


def _entry_out(entry: DiaryEntry, foods_by_id: dict[int, Food], recipes_by_id: dict[int, Recipe]) -> schemas.DiaryEntryOut:
    return schemas.DiaryEntryOut(
        id=entry.id,
        entry_date=entry.entry_date,
        meal=entry.meal,
        food_id=entry.food_id,
        food_name=foods_by_id[entry.food_id].name if entry.food_id else None,
        quantity_g=entry.quantity_g,
        recipe_id=entry.recipe_id,
        recipe_name=recipes_by_id[entry.recipe_id].name if entry.recipe_id else None,
        quantity_servings=entry.quantity_servings,
    )


def _expand_to_weighted_foods(
    entries: list[DiaryEntry], foods_by_id: dict[int, Food], recipes_by_id: dict[int, Recipe], db: Session
) -> list[WeightedFood]:
    """A food entry becomes one WeightedFood; a recipe entry expands into
    its ingredients, each scaled by quantity_servings / recipe.servings —
    this lets the same aggregation math used for recipes handle diary
    totals without duplicating it."""
    items: list[WeightedFood] = []
    recipe_ingredient_cache: dict[int, list[RecipeIngredient]] = {}

    for entry in entries:
        if entry.food_id is not None:
            items.append(WeightedFood(foods_by_id[entry.food_id], entry.quantity_g))
        else:
            recipe = recipes_by_id[entry.recipe_id]
            if recipe.id not in recipe_ingredient_cache:
                recipe_ingredient_cache[recipe.id] = (
                    db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
                )
            ingredients = recipe_ingredient_cache[recipe.id]
            missing_ids = {i.food_id for i in ingredients} - foods_by_id.keys()
            if missing_ids:
                for food in db.query(Food).filter(Food.id.in_(missing_ids)).all():
                    foods_by_id[food.id] = food
            items.extend(
                scale_recipe_ingredients(ingredients, recipe.servings, entry.quantity_servings, foods_by_id)
            )

    return items


@router.post("", response_model=schemas.DiaryEntryOut, status_code=201)
def create_entry(
    body: schemas.DiaryEntryCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if body.food_id is not None and db.get(Food, body.food_id) is None:
        raise HTTPException(status_code=422, detail=f"Unknown food id: {body.food_id}")
    if body.recipe_id is not None:
        recipe = db.get(Recipe, body.recipe_id)
        if recipe is None or recipe.user_id != current_user.id:
            raise HTTPException(status_code=422, detail=f"Unknown recipe id: {body.recipe_id}")

    entry = DiaryEntry(
        user_id=current_user.id,
        entry_date=body.entry_date,
        meal=body.meal,
        food_id=body.food_id,
        quantity_g=body.quantity_g,
        recipe_id=body.recipe_id,
        quantity_servings=body.quantity_servings,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    foods_by_id = {entry.food_id: db.get(Food, entry.food_id)} if entry.food_id else {}
    recipes_by_id = {entry.recipe_id: db.get(Recipe, entry.recipe_id)} if entry.recipe_id else {}
    return _entry_out(entry, foods_by_id, recipes_by_id)


@router.get("", response_model=schemas.DiarySummaryOut)
def get_day(entry_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = (
        db.query(DiaryEntry)
        .filter(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date == entry_date)
        .all()
    )

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    entries_out = [_entry_out(e, foods_by_id, recipes_by_id) for e in entries]

    items = _expand_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)
    all_food_ids = [item.food.id for item in items]
    rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    profile = (current_user.sex, current_user.is_pregnant, current_user.is_lactating)
    totals = aggregate_nutrients(items, by_food_id)  # divide_by=1 — this is a day total, not per-serving

    nutrients_out = []
    for key, amount in totals.items():
        nutrient_def = NUTRIENTS.get(key)
        if nutrient_def is None:
            continue
        drv = resolve_drv(key, profile)
        nutrients_out.append(
            schemas.NutrientAmountOut(
                key=key,
                name=nutrient_def.name,
                unit=nutrient_def.unit,
                amount=amount,
                adult_drv=drv,
                percent_drv=(amount / drv * 100) if drv else None,
            )
        )
    nutrients_out.sort(key=lambda n: n.name)

    return schemas.DiarySummaryOut(entries=entries_out, nutrients=nutrients_out)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    db.delete(entry)
    db.commit()
