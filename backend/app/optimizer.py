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
ranking axis.

Cost: `prices_by_food_id`, when the caller supplies it (from the signed-in
user's own FoodPrice rows — optional, user-entered), attaches a real
estimated cost to each suggestion and can filter out ones that would
exceed a stated `max_additional_cost`. When a candidate has no price on
file, `estimated_cost` is left `None` rather than defaulting to 0 or being
silently excluded — an unpriced suggestion still gets shown (nutritionally
it may be the best option), just without a cost figure attached, same
"don't fabricate, don't hide" convention as the rest of this app.

Deliberately still not implemented, because there is no real data behind
them and fabricating one would violate the same convention: **prep time**
(no per-food/recipe time-to-prepare data exists anywhere in the schema),
**dietary restriction / allergy filtering** (foods have no allergen or
diet-tag data — USDA FDC doesn't supply it either), **family-size
scaling** (quantities here are per-person; scaling is just multiplication
the caller can do, not something the optimizer needs to model), and
**preferred store** (FoodPrice is one price per food per user, not priced
per store — there's no store dimension to select). Each would need a real
schema addition before it could be built honestly; see
docs/optimizer-constraints-scoping.md.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_nutrients
from .models import Food, FoodNutrient, FoodPrice

ADD_TRIAL_QUANTITY_G = 30.0
CANDIDATE_SHORTLIST_SIZE = 8


def load_prices_by_food_id(db: Session, user_id: int) -> dict[int, float]:
    """Real price-per-100g for every food this user has priced (FoodPrice is
    optional and user-entered — see food_prices.py). Loaded unfiltered by
    food id (a personal price list) since swap candidates are only
    discovered inside suggest_meal_optimizations itself, after this would
    otherwise need to run. Shared by the diary and meal-plan optimize
    endpoints so both compute cost the same way."""
    prices = db.query(FoodPrice).filter(FoodPrice.user_id == user_id).all()
    return {p.food_id: p.package_price / p.package_quantity_g * 100 for p in prices}


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
    # None when the food (or, for a swap, either food) has no price on file
    # for this user — never fabricated, never defaulted to 0
    estimated_cost: float | None
    rationale: str


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


def _add_cost(prices_by_food_id: dict[int, float] | None, food_id: int, quantity_g: float) -> float | None:
    if not prices_by_food_id or food_id not in prices_by_food_id:
        return None
    return prices_by_food_id[food_id] * quantity_g / 100


def _swap_cost(
    prices_by_food_id: dict[int, float] | None, old_food_id: int, new_food_id: int, quantity_g: float
) -> float | None:
    if not prices_by_food_id or old_food_id not in prices_by_food_id or new_food_id not in prices_by_food_id:
        return None
    return (prices_by_food_id[new_food_id] - prices_by_food_id[old_food_id]) * quantity_g / 100


def _target_label(target_nutrient_name: str | None, target_nutrient_key: str) -> str:
    return target_nutrient_name or target_nutrient_key


def suggest_meal_optimizations(
    db: Session,
    other_items: list[WeightedFood],
    swappable_items: list[WeightedFood],
    by_food_id: dict[int, list[FoodNutrient]],
    target_nutrient_key: str,
    target_drv: float,
    gap_candidates: list[Food],
    limit: int = 5,
    target_nutrient_name: str | None = None,
    prices_by_food_id: dict[int, float] | None = None,
    max_additional_cost: float | None = None,
) -> list[OptimizationSuggestion]:
    """other_items: every other meal's expanded items that day, plus any
    recipe-derived items from the meal being optimized (not swap-eligible
    — swapping one ingredient inside an eaten recipe isn't this feature's
    job). swappable_items: this meal's directly-logged (non-recipe) food
    items, the only ones eligible to be swapped out.

    prices_by_food_id: real price-per-100g for the calling user's own
    FoodPrice rows (never fabricated — see module docstring). When given,
    max_additional_cost drops suggestions whose *known* cost exceeds it;
    suggestions with no price on file are never dropped for cost reasons,
    since excluding them would bias results toward whatever happens to be
    priced rather than what's nutritionally best."""
    label = _target_label(target_nutrient_name, target_nutrient_key)
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
        estimated_cost = _add_cost(prices_by_food_id, candidate.id, ADD_TRIAL_QUANTITY_G)
        if max_additional_cost is not None and estimated_cost is not None and estimated_cost > max_additional_cost:
            continue
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
                estimated_cost=estimated_cost,
                rationale=(
                    f"Adding {ADD_TRIAL_QUANTITY_G:.0f}g of {candidate.name} raises {label} from "
                    f"{before_percent:.0f}% to {after_percent:.0f}% of target — a real simulated change, "
                    f"not an estimate from this food's raw content alone."
                ),
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
            estimated_cost = _swap_cost(prices_by_food_id, item.food.id, candidate.id, item.quantity_g)
            if max_additional_cost is not None and estimated_cost is not None and estimated_cost > max_additional_cost:
                continue
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
                    estimated_cost=estimated_cost,
                    rationale=(
                        f"Swapping {item.food.name} for {candidate.name} raises {label} from "
                        f"{before_percent:.0f}% to {after_percent:.0f}% of target — same family of food, "
                        f"same quantity, actually simulated rather than assumed interchangeable."
                    ),
                )
            )

    suggestions.sort(key=lambda s: s.improvement, reverse=True)
    return suggestions[:limit]
