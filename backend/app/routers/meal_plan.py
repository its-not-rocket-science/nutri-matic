from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import aggregate_food_grams, expand_entries_to_weighted_foods
from ..auth import get_current_user
from ..database import get_db
from ..models import DiaryEntry, Food, FoodPrice, MealPlanEntry, Recipe, User
from ..optimizer import load_prices_by_food_id, suggest_meal_optimizations
from .diary import _compute_nutrient_gaps, _find_worst_gap, _rank_foods_by_nutrient, _rank_recipes_by_nutrient

router = APIRouter(prefix="/api/meal-plan", tags=["meal-plan"])


def _entry_out(
    entry: MealPlanEntry, foods_by_id: dict[int, Food], recipes_by_id: dict[int, Recipe]
) -> schemas.MealPlanEntryOut:
    return schemas.MealPlanEntryOut(
        id=entry.id,
        plan_date=entry.plan_date,
        meal=entry.meal,
        food_id=entry.food_id,
        food_name=foods_by_id[entry.food_id].name if entry.food_id else None,
        quantity_g=entry.quantity_g,
        recipe_id=entry.recipe_id,
        recipe_name=recipes_by_id[entry.recipe_id].name if entry.recipe_id else None,
        quantity_servings=entry.quantity_servings,
    )


def _validate_food_or_recipe(food_id: int | None, recipe_id: int | None, current_user: User, db: Session):
    if food_id is not None and db.get(Food, food_id) is None:
        raise HTTPException(status_code=422, detail=f"Unknown food id: {food_id}")
    if recipe_id is not None:
        recipe = db.get(Recipe, recipe_id)
        if recipe is None or recipe.user_id != current_user.id:
            raise HTTPException(status_code=422, detail=f"Unknown recipe id: {recipe_id}")


@router.post("", response_model=schemas.MealPlanEntryOut, status_code=201)
def create_entry(
    body: schemas.MealPlanEntryCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _validate_food_or_recipe(body.food_id, body.recipe_id, current_user, db)

    entry = MealPlanEntry(
        user_id=current_user.id,
        plan_date=body.plan_date,
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


def _entries_in_range(start_date: date, end_date: date, current_user: User, db: Session) -> list[MealPlanEntry]:
    return (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.user_id == current_user.id,
            MealPlanEntry.plan_date >= start_date,
            MealPlanEntry.plan_date <= end_date,
        )
        .all()
    )


@router.get("", response_model=list[schemas.MealPlanEntryOut])
def list_entries(
    start_date: date, end_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    entries = _entries_in_range(start_date, end_date, current_user, db)

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    return [_entry_out(e, foods_by_id, recipes_by_id) for e in entries]


@router.get("/shopping-list", response_model=schemas.ShoppingListOut)
def get_shopping_list(
    start_date: date, end_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    entries = _entries_in_range(start_date, end_date, current_user, db)

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)
    totals = aggregate_food_grams(items)

    prices_by_food_id = {
        p.food_id: p
        for p in db.query(FoodPrice).filter(FoodPrice.user_id == current_user.id, FoodPrice.food_id.in_(totals)).all()
    }

    shopping_items = []
    total_cost = 0.0
    items_missing_price = 0
    for food_id, quantity_g in totals.items():
        price = prices_by_food_id.get(food_id)
        if price is not None:
            price_per_100g = price.package_price / price.package_quantity_g * 100
            estimated_cost = price_per_100g * quantity_g / 100
            total_cost += estimated_cost
        else:
            price_per_100g = None
            estimated_cost = None
            items_missing_price += 1
        shopping_items.append(
            schemas.ShoppingListItemOut(
                food_id=food_id,
                food_name=foods_by_id[food_id].name,
                quantity_g=quantity_g,
                price_per_100g=price_per_100g,
                estimated_cost=estimated_cost,
            )
        )
    shopping_items.sort(key=lambda i: i.food_name)

    return schemas.ShoppingListOut(items=shopping_items, total_cost=total_cost, items_missing_price=items_missing_price)


@router.get("/optimize", response_model=schemas.PlanOptimizationOut | None)
def get_plan_optimization(
    start_date: date,
    end_date: date,
    limit: int = 5,
    max_additional_cost: float | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Week-level counterpart to the diary's /meal-optimize: real, simulated
    additions and same-family swaps across a whole meal-plan date range that
    measurably close the range's single worst nutrient gap. Unlike the
    diary version there's no single "meal" to exclude the rest of — every
    directly-planned (non-recipe) food in the range is swap-eligible, and
    recipe-derived items are fixed (same reasoning as the diary: swapping
    one ingredient inside a planned recipe isn't this feature's job).
    Returns None if the range has no entries, or there's no gap to target."""
    entries = _entries_in_range(start_date, end_date, current_user, db)
    if not entries:
        return None

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    gaps = _compute_nutrient_gaps(entries, foods_by_id, recipes_by_id, current_user, db)
    worst = _find_worst_gap(gaps.nutrients_out)
    if worst is None:
        return None

    recipe_entries = [e for e in entries if e.recipe_id is not None]
    food_entries = [e for e in entries if e.food_id is not None]

    other_items = expand_entries_to_weighted_foods(recipe_entries, foods_by_id, recipes_by_id, db)
    swappable_items = expand_entries_to_weighted_foods(food_entries, foods_by_id, recipes_by_id, db)

    already_in_plan = {item.food.id for item in swappable_items}
    gap_candidates = [
        food
        for food, _amount in _rank_foods_by_nutrient(db, worst.key, 8, current_user)
        if food.id not in already_in_plan
    ]

    already_planned_recipe_ids = {e.recipe_id for e in recipe_entries}
    recipe_gap_candidates = [
        (recipe, items)
        for recipe, items in _rank_recipes_by_nutrient(db, worst.key, 8, current_user)
        if recipe.id not in already_planned_recipe_ids
    ]

    prices_by_food_id = load_prices_by_food_id(db, current_user.id)

    suggestions = suggest_meal_optimizations(
        db,
        other_items,
        swappable_items,
        gaps.by_food_id,
        worst.key,
        worst.adult_drv or 0.0,
        gap_candidates,
        limit,
        target_nutrient_name=worst.name,
        prices_by_food_id=prices_by_food_id,
        max_additional_cost=max_additional_cost,
        recipe_gap_candidates=recipe_gap_candidates,
    )

    return schemas.PlanOptimizationOut(
        start_date=start_date,
        end_date=end_date,
        target_nutrient_key=worst.key,
        target_nutrient_name=worst.name,
        suggestions=[
            schemas.OptimizationSuggestionOut(
                action=s.action,
                food_id=s.food_id,
                food_name=s.food_name,
                quantity_g=s.quantity_g,
                replaces_food_id=s.replaces_food_id,
                replaces_food_name=s.replaces_food_name,
                before_percent_drv=s.before_percent_drv,
                after_percent_drv=s.after_percent_drv,
                improvement=s.improvement,
                calories_added=s.calories_added,
                improvement_per_100kcal=s.improvement_per_100kcal,
                estimated_cost=s.estimated_cost,
                rationale=s.rationale,
                recipe_id=s.recipe_id,
                quantity_servings=s.quantity_servings,
            )
            for s in suggestions
        ],
    )


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.get(MealPlanEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Meal plan entry not found")
    db.delete(entry)
    db.commit()


@router.post("/{entry_id}/mark-eaten", response_model=schemas.DiaryEntryOut, status_code=201)
def mark_eaten(entry_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.get(MealPlanEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Meal plan entry not found")

    diary_entry = DiaryEntry(
        user_id=current_user.id,
        entry_date=entry.plan_date,
        meal=entry.meal,
        food_id=entry.food_id,
        quantity_g=entry.quantity_g,
        recipe_id=entry.recipe_id,
        quantity_servings=entry.quantity_servings,
    )
    db.add(diary_entry)
    db.delete(entry)
    db.commit()
    db.refresh(diary_entry)

    foods_by_id = {diary_entry.food_id: db.get(Food, diary_entry.food_id)} if diary_entry.food_id else {}
    recipes_by_id = {diary_entry.recipe_id: db.get(Recipe, diary_entry.recipe_id)} if diary_entry.recipe_id else {}
    return schemas.DiaryEntryOut(
        id=diary_entry.id,
        entry_date=diary_entry.entry_date,
        meal=diary_entry.meal,
        food_id=diary_entry.food_id,
        food_name=foods_by_id[diary_entry.food_id].name if diary_entry.food_id else None,
        quantity_g=diary_entry.quantity_g,
        recipe_id=diary_entry.recipe_id,
        recipe_name=recipes_by_id[diary_entry.recipe_id].name if diary_entry.recipe_id else None,
        quantity_servings=diary_entry.quantity_servings,
    )
