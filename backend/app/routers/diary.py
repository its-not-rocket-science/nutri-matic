from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..aggregation import aggregate_nutrients, expand_entries_to_weighted_foods
from ..auth import get_current_user
from ..bioavailability import (
    IronSplit,
    estimate_calcium_phosphorus,
    estimate_meal_iron_absorption,
    is_meat_fish_poultry,
    split_food_iron,
)
from ..database import get_db
from ..energy import calculate_eer
from ..models import DiaryEntry, Food, FoodNutrient, Recipe, User
from ..nutrients import NUTRIENTS, resolve_drv
from ..trends import GroupBy, bucket_day_totals

router = APIRouter(prefix="/api/diary", tags=["diary"])

MEALS = ("breakfast", "lunch", "dinner", "snack")


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

    items = expand_entries_to_weighted_foods(entries, foods_by_id, recipes_by_id, db)
    all_food_ids = [item.food.id for item in items]
    rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    profile = (current_user.sex, current_user.is_pregnant, current_user.is_lactating)
    totals = aggregate_nutrients(items, by_food_id)  # divide_by=1 — this is a day total, not per-serving
    eer = calculate_eer(current_user)

    nutrients_out = []
    for key, amount in totals.items():
        nutrient_def = NUTRIENTS.get(key)
        if nutrient_def is None:
            continue
        # energy's target is a personalized BMR+activity calculation, not a
        # sex/life-stage table lookup — resolve_drv() correctly returns None
        # for it (see nutrients.py), so it's handled separately here
        drv = eer if key == "energy" else resolve_drv(key, profile)
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

    iron_out: list[schemas.MealIronBioavailabilityOut] = []
    for meal in MEALS:
        meal_entries = [e for e in entries if e.meal == meal]
        if not meal_entries:
            continue
        meal_items = expand_entries_to_weighted_foods(meal_entries, foods_by_id, recipes_by_id, db)

        iron_splits: list[IronSplit] = []
        vitamin_c_mg = 0.0
        has_mfp = False
        for item in meal_items:
            nutrients_by_key = {row.nutrient_key: row.amount_per_100g for row in by_food_id.get(item.food.id, [])}
            scale = item.quantity_g / 100
            total_iron_mg = nutrients_by_key.get("iron", 0.0) * scale
            measured_heme_mg = nutrients_by_key.get("iron_heme")
            measured_non_heme_mg = nutrients_by_key.get("iron_non_heme")
            if total_iron_mg > 0 or measured_heme_mg is not None or measured_non_heme_mg is not None:
                iron_splits.append(
                    split_food_iron(
                        item.food.name,
                        total_iron_mg,
                        measured_heme_mg * scale if measured_heme_mg is not None else None,
                        measured_non_heme_mg * scale if measured_non_heme_mg is not None else None,
                    )
                )
            vitamin_c_mg += nutrients_by_key.get("vitamin_c", 0.0) * scale
            if is_meat_fish_poultry(item.food.name):
                has_mfp = True

        estimate = estimate_meal_iron_absorption(iron_splits, vitamin_c_mg, has_mfp)
        if estimate is not None:
            iron_out.append(
                schemas.MealIronBioavailabilityOut(
                    meal=meal,
                    heme_iron_mg=estimate.heme_iron_mg,
                    non_heme_iron_mg=estimate.non_heme_iron_mg,
                    vitamin_c_mg=estimate.vitamin_c_mg,
                    absorbed_heme_mg=estimate.absorbed_heme_mg,
                    absorbed_non_heme_mg=estimate.absorbed_non_heme_mg,
                    absorbed_total_mg=estimate.absorbed_total_mg,
                    non_heme_absorption_tier=estimate.non_heme_absorption_tier,
                    iron_split_source=estimate.iron_split_source,
                )
            )

    cp_estimate = estimate_calcium_phosphorus(totals.get("calcium", 0.0), totals.get("phosphorus", 0.0))
    calcium_phosphorus = (
        schemas.CalciumPhosphorusOut(
            calcium_mg=cp_estimate.calcium_mg,
            phosphorus_mg=cp_estimate.phosphorus_mg,
            ratio=cp_estimate.ratio,
            guidance=cp_estimate.guidance,
        )
        if cp_estimate is not None
        else None
    )

    return schemas.DiarySummaryOut(
        entries=entries_out, nutrients=nutrients_out, iron_bioavailability=iron_out, calcium_phosphorus=calcium_phosphorus
    )


@router.get("/quick-add", response_model=schemas.QuickAddOut)
def get_quick_add(limit: int = 10, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = db.query(DiaryEntry).filter(DiaryEntry.user_id == current_user.id).all()

    groups: dict[tuple[str, int], dict] = {}
    for entry in entries:
        key = ("food", entry.food_id) if entry.food_id is not None else ("recipe", entry.recipe_id)
        group = groups.setdefault(key, {"count": 0, "last_entry": entry})
        group["count"] += 1
        if entry.entry_date > group["last_entry"].entry_date:
            group["last_entry"] = entry

    food_ids = {obj_id for kind, obj_id in groups if kind == "food"}
    recipe_ids = {obj_id for kind, obj_id in groups if kind == "recipe"}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    items: list[schemas.QuickAddItemOut] = []
    for (kind, obj_id), group in groups.items():
        # a recipe logged in the past may since have been deleted — skip rather than
        # surface a quick-add entry that would 422 when applied. Foods aren't deletable.
        if kind == "recipe" and obj_id not in recipes_by_id:
            continue
        entry = group["last_entry"]
        items.append(
            schemas.QuickAddItemOut(
                food_id=entry.food_id,
                food_name=foods_by_id[entry.food_id].name if entry.food_id else None,
                recipe_id=entry.recipe_id,
                recipe_name=recipes_by_id[entry.recipe_id].name if entry.recipe_id else None,
                quantity_g=entry.quantity_g,
                quantity_servings=entry.quantity_servings,
                last_logged=entry.entry_date,
                log_count=group["count"],
            )
        )

    recent = sorted(items, key=lambda i: i.last_logged, reverse=True)[:limit]
    frequent = sorted(items, key=lambda i: (i.log_count, i.last_logged), reverse=True)[:limit]

    return schemas.QuickAddOut(recent=recent, frequent=frequent)


@router.get("/trends", response_model=schemas.DiaryTrendsOut)
def get_trends(
    start_date: date,
    end_date: date,
    group_by: GroupBy = "week",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(DiaryEntry)
        .filter(
            DiaryEntry.user_id == current_user.id,
            DiaryEntry.entry_date >= start_date,
            DiaryEntry.entry_date <= end_date,
        )
        .all()
    )

    entries_by_date: dict[date, list[DiaryEntry]] = {}
    for entry in entries:
        entries_by_date.setdefault(entry.entry_date, []).append(entry)

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    profile = (current_user.sex, current_user.is_pregnant, current_user.is_lactating)
    eer = calculate_eer(current_user)

    day_totals: dict[date, dict[str, float]] = {}
    for day, day_entries in entries_by_date.items():
        items = expand_entries_to_weighted_foods(day_entries, foods_by_id, recipes_by_id, db)
        all_food_ids = [item.food.id for item in items]
        rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all()
        by_food_id: dict[int, list[FoodNutrient]] = {}
        for row in rows:
            by_food_id.setdefault(row.food_id, []).append(row)
        day_totals[day] = aggregate_nutrients(items, by_food_id)

    buckets_out = []
    for bucket in bucket_day_totals(day_totals, group_by):
        nutrients_out = []
        for key, avg_amount in bucket.avg_nutrients.items():
            nutrient_def = NUTRIENTS.get(key)
            if nutrient_def is None:
                continue
            drv = eer if key == "energy" else resolve_drv(key, profile)
            nutrients_out.append(
                schemas.TrendNutrientOut(
                    key=key,
                    name=nutrient_def.name,
                    unit=nutrient_def.unit,
                    avg_amount=avg_amount,
                    adult_drv=drv,
                    avg_percent_drv=(avg_amount / drv * 100) if drv else None,
                )
            )
        nutrients_out.sort(key=lambda n: n.name)
        buckets_out.append(
            schemas.TrendBucketOut(
                bucket_start=bucket.bucket_start,
                bucket_end=bucket.bucket_end,
                logged_days=bucket.logged_days,
                nutrients=nutrients_out,
            )
        )

    return schemas.DiaryTrendsOut(group_by=group_by, buckets=buckets_out)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    db.delete(entry)
    db.commit()
