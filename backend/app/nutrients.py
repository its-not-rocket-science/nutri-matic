"""Reference data for nutrients tracked via the FoodNutrient table (vitamins,
minerals, dietary fibre — anything expressed as a simple amount per 100g,
as opposed to amino acids, which get their own per-gram-protein handling in
reference_patterns.py): which nutrients we track, how to pull them from
USDA FoodData Central, and a daily reference value (DRV) matrix per
nutrient for gap analysis.

fdc_nutrient_nbr values are USDA's nutrient numbers, verified directly
against nutrient.csv in both the Foundation Foods 2026-04-30 and SR Legacy
2018-04 CSV exports. These are meant to be stable across releases, but
aren't always — arachidonic_acid's differs between the two datasets (see
its comment below); ingest_fdc.py's NUTRIENT_NBR_TO_FIELD maps both. Worth
re-diffing nutrient.csv between datasets when adding new nutrients here
rather than assuming a number checked once holds everywhere.

DRV MATRIX: each nutrient has four values — adult_male, adult_female,
pregnant, lactating — rather than one generic-adult figure, so gap
analysis can reflect a user's profile (sex, pregnancy/lactation status;
see resolve_drv() below). UK Reference Nutrient Intake (RNI) is used where
one exists, else EFSA Population Reference Intake / Adequate Intake, else
US RDA/AI (matches README's "UK/EFSA Dietary Reference Values"; US figures
are a last resort). Confidence varies a lot per value — see each
nutrient's comment:
  - Several (vitamin A, calcium, iron, folate, vitamin C) have their
    pregnancy/lactation increment confirmed against a live UK COMA-derived
    source this session — noted as "confirmed" in the comment.
  - Most male/female adult splits come from the same comparison table
    used for the original single-figure DRVs (nutritionalassessment.org/nrv/),
    same caveat as before: consistently reproduced across secondary
    sources, not independently checked against the primary UK/EFSA/US
    documents page-by-page.
  - Where no pregnancy/lactation increment could be found or confidently
    recalled, pregnant/lactating fall back to the adult_female value —
    stated explicitly rather than inventing a plausible-looking increment.
"""

from dataclasses import dataclass, field

DRVProfile = tuple[str | None, bool, bool]  # (sex, is_pregnant, is_lactating)


@dataclass
class NutrientDef:
    name: str
    unit: str  # "mg", "mcg", or "g", as stored (amount_per_100g uses this unit)
    fdc_nutrient_nbr: str
    drv: dict[str, float] = field(default_factory=dict)  # adult_male/adult_female/pregnant/lactating
    drv_source: str = ""


def _drv(male: float, female: float, pregnant: float | None = None, lactating: float | None = None) -> dict[str, float]:
    """pregnant/lactating default to the female value when not given — an
    explicit 'no confirmed increment' rather than an invented one."""
    return {
        "adult_male": male,
        "adult_female": female,
        "pregnant": pregnant if pregnant is not None else female,
        "lactating": lactating if lactating is not None else female,
    }


NUTRIENTS: dict[str, NutrientDef] = {
    # --- fat-soluble vitamins ---
    "vitamin_a": NutrientDef(
        "Vitamin A (RAE)", "mcg", "320",
        _drv(700, 600, pregnant=700, lactating=950),
        "UK RNI; pregnancy (+100mcg to 700) confirmed live this session; lactation figure "
        "(950) recalled from COMA-derived sources, not re-confirmed",
    ),
    "retinol": NutrientDef(
        "Retinol", "mcg", "319", _drv(700, 600, pregnant=700, lactating=950),
        "same DRV as vitamin_a (retinol is its dominant form)",
    ),
    "beta_carotene": NutrientDef("Beta-carotene", "mcg", "321", _drv(0, 0), "no independent DRV — contributes to vitamin_a"),
    "vitamin_d": NutrientDef(
        "Vitamin D", "mcg", "328", _drv(10, 10, pregnant=10, lactating=10),
        "UK RNI — flat 10mcg for all adults since SACN's 2016 update, no pregnancy/lactation increment",
    ),
    "vitamin_e": NutrientDef(
        "Vitamin E", "mg", "323", _drv(15, 15, pregnant=15, lactating=19),
        "US RDA/AI — no UK RNI or EFSA PRI set; lactation figure (19) is the US AI increment",
    ),
    "vitamin_k1": NutrientDef("Vitamin K1 (phylloquinone)", "mcg", "430", _drv(70, 70), "EFSA AI, no confirmed pregnancy/lactation increment"),
    "vitamin_k2": NutrientDef("Vitamin K2 (menaquinone-4)", "mcg", "428", _drv(0, 0), "no independent DRV — contributes to vitamin_k1's role"),
    # --- water-soluble vitamins ---
    "vitamin_c": NutrientDef(
        "Vitamin C", "mg", "401", _drv(40, 40, pregnant=50, lactating=70),
        "UK RNI; pregnancy/lactation increments are commonly-cited COMA figures, moderate confidence",
    ),
    "thiamin": NutrientDef(
        "Thiamin (B1)", "mg", "404", _drv(1.0, 0.8, pregnant=0.9, lactating=1.0),
        "UK RNI; pregnancy increment (+0.1, last trimester only, applied flat here for simplicity) "
        "and lactation increment (+0.2) are commonly-cited COMA figures",
    ),
    "riboflavin": NutrientDef(
        "Riboflavin (B2)", "mg", "405", _drv(1.3, 1.1, pregnant=1.4, lactating=1.6),
        "UK RNI; pregnancy (+0.3) and lactation (+0.5) increments recalled from COMA-derived "
        "sources, not re-confirmed this session",
    ),
    "niacin": NutrientDef(
        "Niacin (B3)", "mg", "406", _drv(16, 12),
        "UK RNI, no confirmed pregnancy/lactation increment — COMA ties niacin to energy intake "
        "rather than a fixed increment, so adult_female is used as-is",
    ),
    "pantothenic_acid": NutrientDef(
        "Pantothenic acid (B5)", "mg", "410", _drv(5, 5, lactating=7),
        "US RDA/AI — no UK RNI or EFSA PRI set; lactation figure (7) is the US AI increment",
    ),
    "vitamin_b6": NutrientDef(
        "Vitamin B6", "mg", "415", _drv(1.4, 1.2),
        "UK RNI, no confirmed pregnancy/lactation increment",
    ),
    "biotin": NutrientDef("Biotin (B7)", "mcg", "416", _drv(30, 30), "US RDA/AI — no UK RNI or EFSA PRI set, no confirmed increment"),
    "folate": NutrientDef(
        "Folate (DFE)", "mcg", "435", _drv(200, 200, pregnant=300, lactating=260),
        "UK RNI; pregnancy increment (+100 to 300) is well-established public health guidance "
        "(distinct from the separate 400mcg supplement advice for neural tube defect prevention); "
        "lactation figure (260) is a commonly-cited COMA increment",
    ),
    "vitamin_b12": NutrientDef(
        "Vitamin B12", "mcg", "418", _drv(1.5, 1.5, lactating=2.0),
        "UK RNI, no pregnancy increment (UK COMA position — the US DRI does increment, UK "
        "doesn't); lactation increment (+0.5) commonly cited",
    ),
    "choline": NutrientDef(
        "Choline", "mg", "421", _drv(400, 400, pregnant=480, lactating=520),
        "approx. EFSA AI; pregnancy/lactation figures are EFSA AI increments, moderate confidence",
    ),
    # --- minerals ---
    "calcium": NutrientDef(
        "Calcium", "mg", "301", _drv(700, 700, pregnant=700, lactating=1250),
        "UK RNI; no pregnancy increment and +550mg lactation increment both confirmed live this session",
    ),
    "iron": NutrientDef(
        "Iron", "mg", "303", _drv(8.7, 14.8, pregnant=14.8, lactating=14.8),
        "UK RNI; no pregnancy increment confirmed live this session (UK position: absorption "
        "efficiency rises to meet demand). Lactation also left at the female baseline — no "
        "confirmed UK increment found",
    ),
    "iron_heme": NutrientDef("Iron, haem", "mg", "364", _drv(0, 0), "no independent DRV — subset of iron"),
    "iron_non_heme": NutrientDef("Iron, non-haem", "mg", "365", _drv(0, 0), "no independent DRV — subset of iron"),
    "magnesium": NutrientDef(
        "Magnesium", "mg", "304", _drv(300, 270),
        "UK RNI, no confirmed pregnancy/lactation increment",
    ),
    "phosphorus": NutrientDef("Phosphorus", "mg", "305", _drv(550, 550), "UK RNI, flat across groups"),
    "potassium": NutrientDef("Potassium", "mg", "306", _drv(3500, 3500), "UK RNI, flat across groups"),
    "zinc": NutrientDef(
        "Zinc", "mg", "309", _drv(9.5, 7.0, lactating=13.0),
        "UK RNI; lactation increment (to 13, first 4 months) is a commonly-cited COMA figure, "
        "no confirmed pregnancy increment",
    ),
    "copper": NutrientDef("Copper", "mg", "312", _drv(1.5, 1.5), "EFSA PRI — no UK RNI, no confirmed sex/life-stage split"),
    "manganese": NutrientDef("Manganese", "mg", "315", _drv(2.0, 2.0), "US RDA/AI — no UK RNI or EFSA PRI, no confirmed split"),
    "selenium": NutrientDef(
        "Selenium", "mcg", "317", _drv(75, 60, lactating=75),
        "UK RNI; lactation increment (+15) is a commonly-cited COMA figure, no confirmed "
        "pregnancy increment",
    ),
    "iodine": NutrientDef(
        "Iodine", "mcg", "314", _drv(140, 140),
        "UK RNI, flat across groups — UK (unlike WHO) sets no pregnancy/lactation increment",
    ),
    # --- dietary fibre ---
    # "Fiber, total dietary" (nbr 291) used rather than the newer AOAC 2011.25
    # method (nbr 293) — 291 is the one present in both Foundation Foods and
    # SR Legacy, avoiding the ambiguity of two methods for the same food.
    "fiber_total": NutrientDef(
        "Fibre, total", "g", "291", _drv(30, 30),
        "UK SACN/NHS recommendation (30g/day), flat across groups",
    ),
    "fiber_soluble": NutrientDef("Fibre, soluble", "g", "295", _drv(0, 0), "no independent DRV — subset of fiber_total"),
    "fiber_insoluble": NutrientDef("Fibre, insoluble", "g", "297", _drv(0, 0), "no independent DRV — subset of fiber_total"),
    "resistant_starch": NutrientDef("Resistant starch", "g", "283", _drv(0, 0), "prebiotic fibre — no established DRV"),
    "inulin": NutrientDef("Inulin", "g", "806", _drv(0, 0), "prebiotic fibre — no established DRV"),
    "beta_glucan": NutrientDef("Beta-glucan", "g", "276", _drv(0, 0), "prebiotic fibre — no established DRV"),
    # --- fats ---
    "fat_total": NutrientDef("Total fat", "g", "204", _drv(95, 70), "UK population reference (~33% food energy)"),
    "saturated_fat": NutrientDef("Saturated fat", "g", "606", _drv(30, 30), "UK SACN recommendation (<30g/day average adult)"),
    "monounsaturated_fat": NutrientDef("Monounsaturated fat", "g", "645", _drv(0, 0), "no established individual DRV"),
    "polyunsaturated_fat": NutrientDef("Polyunsaturated fat", "g", "646", _drv(0, 0), "no established individual DRV"),
    # omega-3
    "ala": NutrientDef("ALA (18:3 n-3)", "g", "851", _drv(2.0, 2.0), "EFSA AI, ~2g/day, no confirmed sex split"),
    "epa": NutrientDef(
        "EPA (20:5 n-3)", "g", "629", _drv(0, 0),
        "no individual DRV — EFSA/WHO guidance is a combined EPA+DHA target (~250-500mg/day), not split per acid",
    ),
    "dha": NutrientDef("DHA (22:6 n-3)", "g", "621", _drv(0, 0), "no individual DRV — see epa's note on the combined target"),
    # omega-6
    "la": NutrientDef("LA (18:2 n-6)", "g", "675", _drv(10.0, 10.0), "EFSA AI, ~10g/day, no confirmed sex split"),
    # nutrient_nbr for this one differs by FDC release: 855 in Foundation
    # Foods 2026-04-30, 853 in SR Legacy 2018-04 — both verified directly
    # against nutrient.csv; ingest_fdc.py maps both to this key.
    "arachidonic_acid": NutrientDef("Arachidonic acid (20:4 n-6)", "g", "855", _drv(0, 0), "no established DRV"),
}

# nutrients with no independent DRV in any variant (their intake matters,
# but %DRV gap analysis isn't meaningful for them individually)
NO_DRV = {key for key, d in NUTRIENTS.items() if not any(d.drv.values())}


def resolve_drv(nutrient_key: str, profile: DRVProfile | None = None) -> float | None:
    """Look up a nutrient's DRV for a given profile.

    profile is (sex, is_pregnant, is_lactating); None (no signed-in user /
    no profile set) resolves to the adult_female figure — the same value
    the public, unauthenticated /api/foods/{id}/nutrients endpoint has
    always shown, so that behavior doesn't change for anonymous browsing.
    """
    nutrient_def = NUTRIENTS.get(nutrient_key)
    if nutrient_def is None or not nutrient_def.drv:
        return None

    if profile is None:
        variant = "adult_female"
    else:
        sex, is_pregnant, is_lactating = profile
        if is_lactating:
            variant = "lactating"
        elif is_pregnant:
            variant = "pregnant"
        elif sex == "male":
            variant = "adult_male"
        else:
            variant = "adult_female"

    value = nutrient_def.drv.get(variant, 0)
    return value or None
