"""Meal optimization — Nutri-Matic's flagship feature: given one already-
logged meal, suggest real, simulated changes that measurably close the
day's single worst nutrient gap (the same "worst gap" gap_suggestions
identifies elsewhere).

Two kinds of suggestion, matching the classic examples of this idea:

- **Add** a food, at a fixed 30g trial quantity, from the same
  gap-ranked candidate pool gap_suggestions already computes.
- **Swap** a food already in the meal for a same-family alternative —
  foods sharing the first comma-separated segment of their USDA name
  (e.g. "Rice, white, ..." vs "Rice, brown, ..."). This is a real,
  inspectable signal from how USDA names foods, not a fabricated
  "similarity score" — it's deliberately narrow (it won't suggest
  swapping rice for quinoa) rather than guess at interchangeability this
  codebase has no real basis for.

Every suggestion's before/after is genuinely simulated through
aggregate_nutrients — the same machinery the diary endpoints themselves
use — not estimated from the candidate's raw per-100g content alone.
Ranked by improvement (percentage points of %DRV gained), and, where the
change has a calorie cost, improvement per 100kcal — a real computed
ranking axis. "Per cost" and "per serving" ranking (both mentioned as
options for this kind of feature) are deliberately not implemented: food
price is set for very few foods (it's optional, user-entered), and "per
serving" isn't well-defined for a raw addition to a meal — forcing either
would mean fabricating numbers this app has no real basis for computing.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_nutrients
from .models import Food, FoodNutrient

ADD_TRIAL_QUANTITY_G = 30.0
CANDIDATE_SHORTLIST_SIZE = 8


@dataclass
class OptimizationSuggestion:
    action: str  # "add" | "swap"
    food_id: int
    food_name: str
    quantity_g: float
    replaces_food_id: int | None
    replaces_food_name: str | None
    before_percent_drv: float
    after_percent_drv: float
    improvement: float
    calories_added: float
    improvement_per_100kcal: float | None


def _family_key(name: str) -> str:
    return name.split(",")[0].strip().lower()


def _energy_per_100g(by_food_id: dict[int, list[FoodNutrient]], food_id: int) -> float:
    return next((row.amount_per_100g for row in by_food_id.get(food_id, []) if row.nutrient_key == "energy"), 0.0)


def _ensure_nutrients_loaded(db: Session, by_food_id: dict[int, list[FoodNutrient]], food_id: int) -> None:
    if food_id not in by_food_id:
        by_food_id[food_id] = db.query(FoodNutrient).filter(FoodNutrient.food_id == food_id).all()


def _simulate_percent_drv(
    items: list[WeightedFood], by_food_id: dict[int, list[FoodNutrient]], target_nutrient_key: str, target_drv: float
) -> float:
    if target_drv <= 0:
        return 0.0
    totals = aggregate_nutrients(items, by_food_id)
    return totals.get(target_nutrient_key, 0.0) / target_drv * 100


def suggest_meal_optimizations(
    db: Session,
    other_items: list[WeightedFood],
    swappable_items: list[WeightedFood],
    by_food_id: dict[int, list[FoodNutrient]],
    target_nutrient_key: str,
    target_drv: float,
    gap_candidates: list[Food],
    limit: int = 5,
) -> list[OptimizationSuggestion]:
    """other_items: every other meal's expanded items that day, plus any
    recipe-derived items from the meal being optimized (not swap-eligible
    — swapping one ingredient inside an eaten recipe isn't this feature's
    job). swappable_items: this meal's directly-logged (non-recipe) food
    items, the only ones eligible to be swapped out."""
    baseline_items = other_items + swappable_items
    before_percent = _simulate_percent_drv(baseline_items, by_food_id, target_nutrient_key, target_drv)

    suggestions: list[OptimizationSuggestion] = []

    for candidate in gap_candidates[:CANDIDATE_SHORTLIST_SIZE]:
        _ensure_nutrients_loaded(db, by_food_id, candidate.id)
        trial_items = baseline_items + [WeightedFood(candidate, ADD_TRIAL_QUANTITY_G)]
        after_percent = _simulate_percent_drv(trial_items, by_food_id, target_nutrient_key, target_drv)
        improvement = after_percent - before_percent
        if improvement <= 0:
            continue
        calories_added = _energy_per_100g(by_food_id, candidate.id) * ADD_TRIAL_QUANTITY_G / 100
        suggestions.append(
            OptimizationSuggestion(
                action="add",
                food_id=candidate.id,
                food_name=candidate.name,
                quantity_g=ADD_TRIAL_QUANTITY_G,
                replaces_food_id=None,
                replaces_food_name=None,
                before_percent_drv=before_percent,
                after_percent_drv=after_percent,
                improvement=improvement,
                calories_added=calories_added,
                improvement_per_100kcal=(improvement / (calories_added / 100)) if calories_added > 0 else None,
            )
        )

    for idx, item in enumerate(swappable_items):
        family = _family_key(item.food.name)
        if not family:
            continue
        same_family = (
            db.query(Food)
            .filter(Food.id != item.food.id, Food.name.ilike(f"{family},%"))
            .limit(CANDIDATE_SHORTLIST_SIZE)
            .all()
        )
        for candidate in same_family:
            _ensure_nutrients_loaded(db, by_food_id, candidate.id)
            new_swappable = swappable_items[:idx] + [WeightedFood(candidate, item.quantity_g)] + swappable_items[idx + 1 :]
            trial_items = other_items + new_swappable
            after_percent = _simulate_percent_drv(trial_items, by_food_id, target_nutrient_key, target_drv)
            improvement = after_percent - before_percent
            if improvement <= 0:
                continue
            old_energy = _energy_per_100g(by_food_id, item.food.id)
            new_energy = _energy_per_100g(by_food_id, candidate.id)
            calories_added = (new_energy - old_energy) * item.quantity_g / 100
            suggestions.append(
                OptimizationSuggestion(
                    action="swap",
                    food_id=candidate.id,
                    food_name=candidate.name,
                    quantity_g=item.quantity_g,
                    replaces_food_id=item.food.id,
                    replaces_food_name=item.food.name,
                    before_percent_drv=before_percent,
                    after_percent_drv=after_percent,
                    improvement=improvement,
                    calories_added=calories_added,
                    improvement_per_100kcal=(improvement / (calories_added / 100)) if calories_added > 0 else None,
                )
            )

    suggestions.sort(key=lambda s: s.improvement, reverse=True)
    return suggestions[:limit]
