"""Food chemistry checks with real, citable data behind them.

Deliberately scoped to what USDA FoodData Central — the only food-
composition data source this app uses — actually supports:

- **sodium:potassium ratio**: WHO recommends <2000mg sodium and
  >=3510mg potassium per day to reduce hypertension/cardiovascular risk,
  giving a target ratio of about 0.57. Both nutrients are directly
  tracked (see nutrients.py's "sodium"/"potassium" entries), so this is a
  real computed ratio against a real published target, not a guess.
- **leucine threshold**: the minimum leucine in a single meal to maximally
  stimulate muscle protein synthesis is well studied — commonly cited as
  ~2.5g for younger adults, ~3g for older adults (age-related anabolic
  resistance), from Norton & Layman 2006 and widely reproduced since.
  Leucine content is already tracked per food (reference_patterns.py /
  Food.amino_acids), so this is computed directly from real data.
- **protein distribution through the day**: research (e.g. Mamerow et al.
  2014) associates protein spread evenly across meals — each one clearing
  the leucine threshold — with better muscle protein synthesis than the
  same daily total skewed into one large meal. This reuses the leucine
  threshold check per meal rather than inventing a separate "evenness"
  metric.

Explicitly NOT implemented here: phytates, oxalates, tannins. USDA
FoodData Central does not track any of them as nutrients, so there is
nothing to compute from — seeing "no data" here is the honest answer
that any other approach would just be hiding. See the in-app methodology
page's "what this app doesn't do" section.
"""

from dataclasses import dataclass

from .aggregation import WeightedFood

LEUCINE_THRESHOLD_G_YOUNGER_ADULT = 2.5  # Norton & Layman 2006
LEUCINE_THRESHOLD_G_OLDER_ADULT = 3.0  # same source — older-adult anabolic resistance
OLDER_ADULT_AGE_THRESHOLD = 65

WHO_SODIUM_CEILING_MG = 2000  # WHO: less than this per day
# WHO's own hypertension/CVD-risk target (WHO 2012 guideline, ~90mmol/day) —
# deliberately not the same figure as nutrients.py's potassium DRV (3500mg,
# UK RNI, used for general %DRV gap analysis). Both are independently
# correct for their own purpose; they're just two different bodies' numbers
# for two different questions, not a rounding inconsistency to reconcile.
WHO_POTASSIUM_FLOOR_MG = 3510  # WHO: at least this per day
TARGET_SODIUM_POTASSIUM_RATIO = WHO_SODIUM_CEILING_MG / WHO_POTASSIUM_FLOOR_MG  # ~0.57


def leucine_threshold_for_age(age: int | None) -> float:
    """Defaults to the younger-adult threshold when age is unknown (profile
    incomplete) — the lower, easier-to-clear bar, so an incomplete profile
    doesn't make meals look worse than they are."""
    if age is not None and age >= OLDER_ADULT_AGE_THRESHOLD:
        return LEUCINE_THRESHOLD_G_OLDER_ADULT
    return LEUCINE_THRESHOLD_G_YOUNGER_ADULT


@dataclass
class MealProteinDistribution:
    meal: str
    protein_g: float
    leucine_g: float
    leucine_threshold_g: float
    meets_leucine_threshold: bool


def compute_meal_protein_distribution(
    meal: str, items: list[WeightedFood], leucine_threshold_g: float
) -> MealProteinDistribution | None:
    """items should already be expanded (WeightedFood) for just one meal's
    entries. Returns None if the meal contributed no protein — nothing
    meaningful to report, same convention as bioavailability.py."""
    total_protein_g = 0.0
    total_leucine_g = 0.0

    for item in items:
        protein_g = item.food.protein_g_per_100g * item.quantity_g / 100
        if protein_g <= 0:
            continue
        total_protein_g += protein_g

        leucine_mg_per_g_protein = item.food.amino_acids.get("leucine")
        if leucine_mg_per_g_protein is not None:
            total_leucine_g += leucine_mg_per_g_protein * protein_g / 1000

    if total_protein_g <= 0:
        return None

    return MealProteinDistribution(
        meal=meal,
        protein_g=total_protein_g,
        leucine_g=total_leucine_g,
        leucine_threshold_g=leucine_threshold_g,
        meets_leucine_threshold=total_leucine_g >= leucine_threshold_g,
    )


@dataclass
class SodiumPotassiumEstimate:
    sodium_mg: float
    potassium_mg: float
    ratio: float | None
    guidance: str


def estimate_sodium_potassium(sodium_mg: float, potassium_mg: float) -> SodiumPotassiumEstimate | None:
    if sodium_mg <= 0 and potassium_mg <= 0:
        return None

    if potassium_mg <= 0:
        return SodiumPotassiumEstimate(
            sodium_mg=sodium_mg, potassium_mg=potassium_mg, ratio=None,
            guidance="No potassium logged yet, so no ratio can be computed.",
        )

    ratio = sodium_mg / potassium_mg
    target = TARGET_SODIUM_POTASSIUM_RATIO
    if ratio <= target:
        guidance = (
            f"At or below the ratio implied by WHO's targets (<{WHO_SODIUM_CEILING_MG}mg sodium, "
            f"≥{WHO_POTASSIUM_FLOOR_MG}mg potassium per day, ≈{target:.2f})."
        )
    else:
        guidance = (
            f"Above the ratio implied by WHO's targets (≈{target:.2f}) — a higher sodium:potassium "
            "ratio is associated with increased cardiovascular risk in observational studies."
        )

    return SodiumPotassiumEstimate(sodium_mg=sodium_mg, potassium_mg=potassium_mg, ratio=ratio, guidance=guidance)
