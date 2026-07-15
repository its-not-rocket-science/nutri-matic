from dataclasses import dataclass
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
from ..energy import calculate_age, calculate_eer
from ..entitlements import (
    FREE_TIER_SNAPSHOT_LIMIT,
    PLAN_ENTERPRISE,
    PLAN_PAID,
    PLAN_PROFESSIONAL,
    effective_plan,
)
from ..food_chemistry import compute_meal_protein_distribution, estimate_sodium_potassium, leucine_threshold_for_age
from ..methodology import DRV_METHODOLOGY_VERSION, SCORING_METHODOLOGY_VERSION
from ..models import DiaryEntry, DiarySnapshot, Food, FoodNutrient, Recipe, User
from ..nutrients import NUTRIENTS, resolve_drv
from ..optimizer import load_prices_by_food_id, suggest_meal_optimizations
from ..trends import GroupBy, bucket_day_totals

router = APIRouter(prefix="/api/diary", tags=["diary"])

MEALS = ("breakfast", "lunch", "dinner", "snack")

# energy's target is a personalized BMR+activity calculation, not a
# sex/life-stage table lookup — resolve_drv() correctly returns None for it
# (see nutrients.py), so day-total and trend-bucket nutrient rows both need
# to override the source/confidence text on that one nutrient specifically
_ENERGY_DRV_SOURCE = "Personalized target: Mifflin-St Jeor BMR x activity level (see energy.py)"
_ENERGY_DRV_CONFIDENCE = "personalized_calculation"


def _nutrient_amount_out(key: str, nutrient_def, amount: float, drv: float | None) -> schemas.NutrientAmountOut:
    if key == "energy":
        return schemas.NutrientAmountOut.build(
            key, nutrient_def, amount, drv, drv_source=_ENERGY_DRV_SOURCE, drv_confidence=_ENERGY_DRV_CONFIDENCE
        )
    return schemas.NutrientAmountOut.build(key, nutrient_def, amount, drv)


def _trend_nutrient_out(key: str, nutrient_def, avg_amount: float, drv: float | None) -> schemas.TrendNutrientOut:
    if key == "energy":
        return schemas.TrendNutrientOut.build(
            key, nutrient_def, avg_amount, drv, drv_source=_ENERGY_DRV_SOURCE, drv_confidence=_ENERGY_DRV_CONFIDENCE
        )
    return schemas.TrendNutrientOut.build(key, nutrient_def, avg_amount, drv)


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


@router.post("/copy-day", response_model=list[schemas.DiaryEntryOut], status_code=201)
def copy_day(
    source_date: date, target_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Copies every entry logged on source_date onto target_date — additive,
    like the meal-plan/diary-template apply endpoints: existing entries on
    target_date are left alone, never overwritten or deleted."""
    source_entries = (
        db.query(DiaryEntry)
        .filter(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date == source_date)
        .all()
    )

    created: list[DiaryEntry] = []
    for source_entry in source_entries:
        # a recipe logged that day might since have been deleted — skip rather
        # than fail the whole copy for one stale entry
        if source_entry.recipe_id is not None:
            recipe = db.get(Recipe, source_entry.recipe_id)
            if recipe is None or recipe.user_id != current_user.id:
                continue

        entry = DiaryEntry(
            user_id=current_user.id,
            entry_date=target_date,
            meal=source_entry.meal,
            food_id=source_entry.food_id,
            quantity_g=source_entry.quantity_g,
            recipe_id=source_entry.recipe_id,
            quantity_servings=source_entry.quantity_servings,
        )
        db.add(entry)
        created.append(entry)

    db.commit()
    for entry in created:
        db.refresh(entry)

    food_ids = {e.food_id for e in created if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in created if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    return [_entry_out(e, foods_by_id, recipes_by_id) for e in created]


@dataclass
class NutrientGaps:
    nutrients_out: list[schemas.NutrientAmountOut]
    totals: dict[str, float]
    by_food_id: dict[int, list[FoodNutrient]]


def _compute_nutrient_gaps(
    entries: list[DiaryEntry],
    foods_by_id: dict[int, Food],
    recipes_by_id: dict[int, Recipe],
    current_user: User,
    db: Session,
) -> NutrientGaps:
    """Shared by get_day() and the gap-suggestions endpoint — a day's logged
    entries turned into per-nutrient amount + %DRV, using the signed-in
    user's profile (sex, pregnancy/lactation) for DRV resolution."""
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
        nutrients_out.append(_nutrient_amount_out(key, nutrient_def, amount, drv))
    nutrients_out.sort(key=lambda n: n.name)
    return NutrientGaps(nutrients_out=nutrients_out, totals=totals, by_food_id=by_food_id)


def _compute_day_summary(entry_date: date, current_user: User, db: Session) -> schemas.DiarySummaryOut:
    """The full live computation for one diary day — shared by the "Live
    Mode" GET endpoint below and the snapshot-creation endpoint, which
    freezes this exact output rather than recomputing its own version of
    it. See docs/live-vs-snapshot-mode.md."""
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

    gaps = _compute_nutrient_gaps(entries, foods_by_id, recipes_by_id, current_user, db)
    nutrients_out, totals, by_food_id = gaps.nutrients_out, gaps.totals, gaps.by_food_id

    leucine_threshold_g = leucine_threshold_for_age(calculate_age(current_user))

    iron_out: list[schemas.MealIronBioavailabilityOut] = []
    protein_distribution_out: list[schemas.MealProteinDistributionOut] = []
    for meal in MEALS:
        meal_entries = [e for e in entries if e.meal == meal]
        if not meal_entries:
            continue
        meal_items = expand_entries_to_weighted_foods(meal_entries, foods_by_id, recipes_by_id, db)

        distribution = compute_meal_protein_distribution(meal, meal_items, leucine_threshold_g)
        if distribution is not None:
            protein_distribution_out.append(
                schemas.MealProteinDistributionOut(
                    meal=distribution.meal,
                    protein_g=distribution.protein_g,
                    leucine_g=distribution.leucine_g,
                    leucine_threshold_g=distribution.leucine_threshold_g,
                    meets_leucine_threshold=distribution.meets_leucine_threshold,
                )
            )

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

    nak_estimate = estimate_sodium_potassium(totals.get("sodium", 0.0), totals.get("potassium", 0.0))
    sodium_potassium = (
        schemas.SodiumPotassiumOut(
            sodium_mg=nak_estimate.sodium_mg,
            potassium_mg=nak_estimate.potassium_mg,
            ratio=nak_estimate.ratio,
            guidance=nak_estimate.guidance,
        )
        if nak_estimate is not None
        else None
    )

    return schemas.DiarySummaryOut(
        entries=entries_out,
        nutrients=nutrients_out,
        iron_bioavailability=iron_out,
        calcium_phosphorus=calcium_phosphorus,
        sodium_potassium=sodium_potassium,
        protein_distribution=protein_distribution_out,
    )


@router.get("", response_model=schemas.DiarySummaryOut)
def get_day(entry_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Live Mode (the only mode this endpoint has ever had): always
    recomputed from current code and data. See /snapshot for Snapshot Mode
    — reproducing a day exactly as scored on the day it was explicitly
    snapshotted."""
    return _compute_day_summary(entry_date, current_user, db)


@router.post("/snapshot", response_model=schemas.DiarySnapshotOut, status_code=201)
def create_snapshot(entry_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Freezes today's live computation for entry_date so it can be
    reproduced later even after methodology_version moves on. Explicit and
    one-shot: snapshots are never taken automatically, and once taken are
    immutable (never silently re-taken/overwritten) — see
    docs/live-vs-snapshot-mode.md for why. 409 if this day is already
    snapshotted; 422 if there's nothing to snapshot (no entries that day);
    403 if a free-plan user has reached FREE_TIER_SNAPSHOT_LIMIT (see
    docs/product-led-growth-review.md — tied to real per-snapshot storage
    cost, not an arbitrary lock)."""
    existing = (
        db.query(DiarySnapshot)
        .filter(DiarySnapshot.user_id == current_user.id, DiarySnapshot.entry_date == entry_date)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This day already has a snapshot — snapshots are immutable")

    if effective_plan(current_user) not in (PLAN_PAID, PLAN_PROFESSIONAL, PLAN_ENTERPRISE):
        snapshot_count = db.query(DiarySnapshot).filter(DiarySnapshot.user_id == current_user.id).count()
        if snapshot_count >= FREE_TIER_SNAPSHOT_LIMIT:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Free accounts are limited to {FREE_TIER_SNAPSHOT_LIMIT} diary snapshots — "
                    "upgrade to Pro for unlimited snapshots"
                ),
            )

    summary = _compute_day_summary(entry_date, current_user, db)
    if not summary.entries:
        raise HTTPException(status_code=422, detail="Nothing logged this day — nothing to snapshot")

    snapshot = DiarySnapshot(
        user_id=current_user.id,
        entry_date=entry_date,
        summary_json=summary.model_dump(mode="json"),
        drv_methodology_version=DRV_METHODOLOGY_VERSION,
        scoring_methodology_version=SCORING_METHODOLOGY_VERSION,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    return schemas.DiarySnapshotOut(
        entry_date=snapshot.entry_date,
        drv_methodology_version=snapshot.drv_methodology_version,
        scoring_methodology_version=snapshot.scoring_methodology_version,
        created_at=snapshot.created_at,
        summary=summary,
    )


@router.get("/snapshot", response_model=schemas.DiarySnapshotOut | None)
def get_snapshot(entry_date: date, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Snapshot Mode: returns the frozen summary exactly as computed at
    snapshot time, or None if this day was never snapshotted (it only ever
    existed in Live Mode — see docs/live-vs-snapshot-mode.md)."""
    snapshot = (
        db.query(DiarySnapshot)
        .filter(DiarySnapshot.user_id == current_user.id, DiarySnapshot.entry_date == entry_date)
        .one_or_none()
    )
    if snapshot is None:
        return None

    return schemas.DiarySnapshotOut(
        entry_date=snapshot.entry_date,
        drv_methodology_version=snapshot.drv_methodology_version,
        scoring_methodology_version=snapshot.scoring_methodology_version,
        created_at=snapshot.created_at,
        summary=schemas.DiarySummaryOut.model_validate(snapshot.summary_json),
    )


def _find_worst_gap(nutrients_out: list[schemas.NutrientAmountOut]) -> schemas.NutrientAmountOut | None:
    """The single lowest-%DRV nutrient for a day, excluding energy — a
    calorie target isn't a "gap" in the same sense. Shared by
    /gap-suggestions and /meal-optimize so they always agree on what
    "the" gap is."""
    candidates = [n for n in nutrients_out if n.percent_drv is not None and n.key != "energy"]
    if not candidates:
        return None
    return min(candidates, key=lambda n: n.percent_drv)


def _rank_foods_by_nutrient(db: Session, nutrient_key: str, limit: int) -> list[tuple[Food, float]]:
    """Real foods carrying the most of a given nutrient per 100g, paired
    with that amount — the candidate pool both /gap-suggestions and
    /meal-optimize draw from."""
    rows = (
        db.query(FoodNutrient)
        .filter(FoodNutrient.nutrient_key == nutrient_key)
        .order_by(FoodNutrient.amount_per_100g.desc())
        .limit(limit)
        .all()
    )
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_([r.food_id for r in rows])).all()}
    return [(foods_by_id[r.food_id], r.amount_per_100g) for r in rows if r.food_id in foods_by_id]


@router.get("/gap-suggestions", response_model=schemas.GapSuggestionOut | None)
def get_gap_suggestions(
    entry_date: date, limit: int = 8, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Picks the single nutrient with the lowest %DRV for the given day
    and ranks real foods by how much of that nutrient they carry per 100g.
    Returns None if nothing's logged yet, or if nothing logged has a DRV to
    compare against."""
    entries = (
        db.query(DiaryEntry)
        .filter(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date == entry_date)
        .all()
    )

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    gaps = _compute_nutrient_gaps(entries, foods_by_id, recipes_by_id, current_user, db)
    worst = _find_worst_gap(gaps.nutrients_out)
    if worst is None:
        return None

    ranked_foods = _rank_foods_by_nutrient(db, worst.key, limit)

    return schemas.GapSuggestionOut(
        nutrient_key=worst.key,
        nutrient_name=worst.name,
        unit=worst.unit,
        percent_drv=worst.percent_drv,
        foods=[
            schemas.FoodNutrientRankOut(food_id=food.id, food_name=food.name, amount_per_100g=amount)
            for food, amount in ranked_foods
        ],
    )


@router.get("/meal-optimize", response_model=schemas.MealOptimizationOut | None)
def get_meal_optimization(
    entry_date: date,
    meal: str,
    limit: int = 5,
    max_additional_cost: float | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Nutri-Matic's flagship feature: real, simulated additions and
    same-family swaps for one logged meal that measurably close the day's
    single worst nutrient gap. See optimizer.py for the full design and
    what's deliberately out of scope (per-cost/per-serving ranking).
    Returns None if the meal has no entries, or there's no gap to target."""
    entries = (
        db.query(DiaryEntry)
        .filter(DiaryEntry.user_id == current_user.id, DiaryEntry.entry_date == entry_date)
        .all()
    )
    meal_entries = [e for e in entries if e.meal == meal]
    if not meal_entries:
        return None

    food_ids = {e.food_id for e in entries if e.food_id is not None}
    recipe_ids = {e.recipe_id for e in entries if e.recipe_id is not None}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    recipes_by_id = {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

    gaps = _compute_nutrient_gaps(entries, foods_by_id, recipes_by_id, current_user, db)
    worst = _find_worst_gap(gaps.nutrients_out)
    if worst is None:
        return None

    other_entries = [e for e in entries if e.meal != meal]
    meal_recipe_entries = [e for e in meal_entries if e.recipe_id is not None]
    meal_food_entries = [e for e in meal_entries if e.food_id is not None]

    other_items = expand_entries_to_weighted_foods(other_entries, foods_by_id, recipes_by_id, db)
    other_items += expand_entries_to_weighted_foods(meal_recipe_entries, foods_by_id, recipes_by_id, db)
    swappable_items = expand_entries_to_weighted_foods(meal_food_entries, foods_by_id, recipes_by_id, db)

    # "add" suggestions shouldn't just be "eat more of what's already in this
    # meal" — that's what the swap suggestions (and simply logging more of
    # it) already cover; excluded here so every add suggestion is a genuinely
    # new option
    already_in_meal = {item.food.id for item in swappable_items}
    gap_candidates = [
        food for food, _amount in _rank_foods_by_nutrient(db, worst.key, 8) if food.id not in already_in_meal
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
    )

    return schemas.MealOptimizationOut(
        meal=meal,
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
            )
            for s in suggestions
        ],
    )


@router.get("/quick-add", response_model=schemas.QuickAddOut)
def get_quick_add(limit: int = 10, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Unbounded over a long-lived account this would scan the user's entire
    # logging history on every call; recent/frequent groupings only need a
    # bounded recent window, so cap it rather than loading every entry ever.
    entries = (
        db.query(DiaryEntry)
        .filter(DiaryEntry.user_id == current_user.id)
        .order_by(DiaryEntry.entry_date.desc())
        .limit(2000)
        .all()
    )

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


def _compute_trends(
    start_date: date, end_date: date, group_by: GroupBy, current_user: User, db: Session
) -> schemas.DiaryTrendsOut:
    """Shared by the Live Mode /trends endpoint below and the clinician
    dashboard's per-client trends view (routers/clinician.py) — same
    reasoning as _compute_day_summary: freeze nothing, just let the caller
    supply whichever User's profile/entries to compute against."""
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

    # expand every day up front so the FoodNutrient lookup below can run once
    # for the whole date range's food set, instead of once per day (which,
    # over a multi-month trend range, meant the same commonly-eaten foods'
    # nutrient rows were re-fetched on every single day they appeared)
    day_items: dict[date, list] = {}
    all_food_ids: set[int] = set()
    for day, day_entries in entries_by_date.items():
        items = expand_entries_to_weighted_foods(day_entries, foods_by_id, recipes_by_id, db)
        day_items[day] = items
        all_food_ids.update(item.food.id for item in items)

    nutrient_rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(all_food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in nutrient_rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    day_totals: dict[date, dict[str, float]] = {
        day: aggregate_nutrients(items, by_food_id) for day, items in day_items.items()
    }

    buckets_out = []
    for bucket in bucket_day_totals(day_totals, group_by):
        nutrients_out = []
        for key, avg_amount in bucket.avg_nutrients.items():
            nutrient_def = NUTRIENTS.get(key)
            if nutrient_def is None:
                continue
            drv = eer if key == "energy" else resolve_drv(key, profile)
            nutrients_out.append(_trend_nutrient_out(key, nutrient_def, avg_amount, drv))
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


@router.get("/trends", response_model=schemas.DiaryTrendsOut)
def get_trends(
    start_date: date,
    end_date: date,
    group_by: GroupBy = "week",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _compute_trends(start_date, end_date, group_by, current_user, db)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Diary entry not found")
    db.delete(entry)
    db.commit()
