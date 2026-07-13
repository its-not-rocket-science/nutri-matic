"""Iron bioavailability estimate (per meal) and calcium:phosphorus ratio
(per day) — the "Bioavailability adjustments" README line, deliberately
scoped to these two since they're the ones with a defensible published
basis to compute from, rather than inventing coefficients for every
enhancer/inhibitor mentioned in the nutrition literature (phytates,
tannins/polyphenols, oxalates are real inhibitors but FDC doesn't track
them as nutrients at all, so there's no data to compute from).

IRON

Real per-food heme/non-heme iron amounts (nutrients.py's iron_heme/
iron_non_heme, FDC nutrient_nbr 364/365) are used when a food actually has
them — but as of this module's ingested USDA data (Foundation Foods
2026-04-30 + SR Legacy 2018-04), *no* food in the DB has those rows: this
specific breakdown just isn't reported in either dataset's food_nutrient
data despite being a defined FDC nutrient. In practice, every food's iron
here goes through the category fallback below. This is checked directly
against food_nutrients in the running DB, not assumed.

Fallback split: a food's total "iron" is treated as 0% heme unless the
food is meat, poultry, or fish, in which case 40% of its iron is treated
as heme — this specific 40% constant, and the fixed 25% heme-iron
absorption rate below, come from the Monsen algorithm (Monsen ER et al.
1978, "Estimation of available dietary iron", Am J Clin Nutr 31:134-141;
adapted as Monsen & Balintfy 1982). Recent work (see e.g. the review cited
in nutritionalassessment.org/bioavailability/) suggests 40% is itself an
approximation that varies by food source — used here anyway as the most
widely-cited single value, and always reported with
iron_split_source="estimated" for meat/fish/poultry foods so this isn't
mistaken for measured data. Plant foods' iron is treated as 100% non-heme
without an "estimated" flag — heme iron is definitionally a component of
animal myoglobin/hemoglobin, not an approximation for foods that have none.

Non-heme iron absorption in the real Monsen model is a continuous/bracketed
function of a meal's ascorbic acid and meat/fish/poultry (MFP) content;
attempts to find the exact published bracket table (rather than just the
general shape) were unsuccessful — see this module's git history/PR
description for the sources checked. Rather than inventing specific
numeric brackets, this uses a plain two-tier simplification built from the
two facts that ARE directly cited: FAO's Human Vitamin and Mineral
Requirements (2004), Chapter 13, states "each meal should preferably
contain at least 25 mg of ascorbic acid" as an absorption-enhancing
target, and that non-heme absorption generally ranges 2-20% depending on
enhancers. This module uses 5% (baseline, no enhancer present) and 10%
(enhanced, if the meal has >=25mg vitamin C or any meat/fish/poultry) —
the low end of FAO's low/medium/high (5%/10%/15%) whole-diet bioavailability
categories, applied per-meal. This is an explicit simplification, not a
transcription of Monsen's or FAO's exact table, and is always reported as
such via the response's non_heme_absorption_tier field.

CALCIUM:PHOSPHORUS

ESPGHAN (European Society for Paediatric Gastroenterology Hepatology and
Nutrition) recommends a dietary calcium:phosphorus ratio of 1:1 to 2:1 by
weight. Newer research in older adults (NHANES 2005-2006 cross-sectional
data) found no association between this ratio and bone mineral density,
so the guidance text here presents the ratio as informational context
rather than a strict target.
"""

from dataclasses import dataclass

# Foods containing myoglobin/hemoglobin — the only foods where any of their
# iron can plausibly be heme iron. Keyword substring match against the
# food's lowercased name; deliberately excludes plant "meat substitute"
# products (checked via the excludes list) since those contain no heme iron
# regardless of naming.
MEAT_FISH_POULTRY_KEYWORDS: tuple[str, ...] = (
    "beef", "pork", "lamb", "veal", "venison", "chicken", "turkey", "duck",
    "goose", "bacon", "sausage", "ham,", "liver", "kidney", "heart,",
    "fish", "salmon", "tuna", "cod", "shrimp", "crab", "shellfish",
    "tilapia", "trout", "lobster", "scallop", "sardine", "anchovy",
    "mussel", "oyster", "clam", "squid", "octopus",
)
MEAT_FISH_POULTRY_EXCLUDES: tuple[str, ...] = ("substitute", "meatless", "imitation", "plant-based", "vegan")

HEME_FRACTION_OF_MFP_IRON = 0.40  # Monsen 1978/1982
HEME_IRON_ABSORPTION = 0.25  # Monsen 1978/1982, fixed regardless of meal composition
NON_HEME_ABSORPTION_BASELINE = 0.05  # FAO (2004) "low bioavailability" diet figure
NON_HEME_ABSORPTION_ENHANCED = 0.10  # FAO (2004) "medium bioavailability" diet figure
VITAMIN_C_ENHANCER_THRESHOLD_MG = 25.0  # FAO (2004) Ch.13 per-meal target


def is_meat_fish_poultry(food_name: str) -> bool:
    name = food_name.lower()
    if any(kw in name for kw in MEAT_FISH_POULTRY_EXCLUDES):
        return False
    return any(kw in name for kw in MEAT_FISH_POULTRY_KEYWORDS)


@dataclass
class IronSplit:
    heme_mg: float
    non_heme_mg: float
    is_estimated: bool  # True if any of heme_mg came from the MFP category fallback rather than measured data


def split_food_iron(food_name: str, total_iron_mg: float, measured_heme_mg: float | None, measured_non_heme_mg: float | None) -> IronSplit:
    """Splits one food's iron contribution into heme/non-heme.

    Prefers real per-food heme/non-heme FoodNutrient values when present
    (measured_heme_mg/measured_non_heme_mg both not None); falls back to
    the MFP category heuristic against total_iron_mg otherwise."""
    if measured_heme_mg is not None and measured_non_heme_mg is not None:
        return IronSplit(measured_heme_mg, measured_non_heme_mg, is_estimated=False)

    if is_meat_fish_poultry(food_name):
        heme = total_iron_mg * HEME_FRACTION_OF_MFP_IRON
        return IronSplit(heme, total_iron_mg - heme, is_estimated=True)

    return IronSplit(0.0, total_iron_mg, is_estimated=False)


@dataclass
class MealIronEstimate:
    heme_iron_mg: float
    non_heme_iron_mg: float
    vitamin_c_mg: float
    absorbed_heme_mg: float
    absorbed_non_heme_mg: float
    non_heme_absorption_tier: str  # "baseline" | "enhanced"
    iron_split_source: str  # "measured" | "estimated"

    @property
    def absorbed_total_mg(self) -> float:
        return self.absorbed_heme_mg + self.absorbed_non_heme_mg


def estimate_meal_iron_absorption(
    iron_splits: list[IronSplit], vitamin_c_mg: float, has_meat_fish_poultry: bool
) -> MealIronEstimate | None:
    """Combines a meal's per-food iron splits into an absorption estimate.

    Returns None if the meal has no iron at all (nothing meaningful to
    report), rather than a zeroed-out result that looks like a real
    finding."""
    heme_mg = sum(s.heme_mg for s in iron_splits)
    non_heme_mg = sum(s.non_heme_mg for s in iron_splits)
    if heme_mg <= 0 and non_heme_mg <= 0:
        return None

    enhanced = vitamin_c_mg >= VITAMIN_C_ENHANCER_THRESHOLD_MG or has_meat_fish_poultry
    non_heme_rate = NON_HEME_ABSORPTION_ENHANCED if enhanced else NON_HEME_ABSORPTION_BASELINE

    return MealIronEstimate(
        heme_iron_mg=heme_mg,
        non_heme_iron_mg=non_heme_mg,
        vitamin_c_mg=vitamin_c_mg,
        absorbed_heme_mg=heme_mg * HEME_IRON_ABSORPTION,
        absorbed_non_heme_mg=non_heme_mg * non_heme_rate,
        non_heme_absorption_tier="enhanced" if enhanced else "baseline",
        iron_split_source="estimated" if any(s.is_estimated for s in iron_splits) else "measured",
    )


CALCIUM_PHOSPHORUS_RATIO_LOW = 1.0
CALCIUM_PHOSPHORUS_RATIO_HIGH = 2.0


@dataclass
class CalciumPhosphorusEstimate:
    calcium_mg: float
    phosphorus_mg: float
    ratio: float
    guidance: str


def estimate_calcium_phosphorus(calcium_mg: float, phosphorus_mg: float) -> CalciumPhosphorusEstimate | None:
    if phosphorus_mg <= 0:
        return None

    ratio = calcium_mg / phosphorus_mg
    if ratio < CALCIUM_PHOSPHORUS_RATIO_LOW:
        guidance = (
            "Phosphorus intake is higher than calcium. ESPGHAN's traditional guidance recommends a "
            "1:1-2:1 calcium:phosphorus ratio, though newer research in older adults found no link "
            "between this ratio and bone density — informational, not a strict target."
        )
    elif ratio <= CALCIUM_PHOSPHORUS_RATIO_HIGH:
        guidance = "Within ESPGHAN's traditionally recommended 1:1-2:1 calcium:phosphorus ratio."
    else:
        guidance = "Calcium notably higher than phosphorus — outside the typical 1:1-2:1 range, but no specific concern is noted in the literature for this direction."

    return CalciumPhosphorusEstimate(calcium_mg=calcium_mg, phosphorus_mg=phosphorus_mg, ratio=ratio, guidance=guidance)
