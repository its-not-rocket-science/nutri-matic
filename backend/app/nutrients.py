"""Reference data for nutrients tracked via the FoodNutrient table (vitamins,
minerals, dietary fibre — anything expressed as a simple amount per 100g,
as opposed to amino acids, which get their own per-gram-protein handling in
reference_patterns.py): which nutrients we track, how to pull them from
USDA FoodData Central, and a single adult daily reference value (DRV) per
nutrient for gap analysis where one applies.

fdc_nutrient_nbr values are USDA's nutrient numbers, verified directly
against nutrient.csv in both the Foundation Foods 2026-04-30 and SR Legacy
2018-04 CSV exports. These are meant to be stable across releases, but
aren't always — arachidonic_acid's differs between the two datasets (see
its comment below); ingest_fdc.py's NUTRIENT_NBR_TO_FIELD maps both. Worth
re-diffing nutrient.csv between datasets when adding new nutrients here
rather than assuming a number checked once holds everywhere.

DRV CAVEAT: this is a single generic-adult baseline, not the age/sex/
pregnancy/lactation-specific matrix the README's "User profiles" feature
will eventually need — that's future work. Each value below is UK
Reference Nutrient Intake (RNI) where one exists, else EFSA Population
Reference Intake / Adequate Intake, else US RDA/AI, in that preference
order (matches README's "UK/EFSA Dietary Reference Values"; US figures
used only as a last resort where UK/EFSA don't set one). Grounded against
a comparison table cross-referencing UK RNI/EFSA PRI/US RDA/WHO-FAO RNI
(nutritionalassessment.org/nrv/); where UK/EFSA gave a male/female range,
the midpoint (or the more conservative higher figure, for iron) is used —
see per-nutrient comments.
"""

from dataclasses import dataclass


@dataclass
class NutrientDef:
    name: str
    unit: str  # "mg", "mcg", or "g", as stored (amount_per_100g uses this unit)
    fdc_nutrient_nbr: str
    adult_drv: float
    drv_source: str


NUTRIENTS: dict[str, NutrientDef] = {
    # --- fat-soluble vitamins ---
    "vitamin_a": NutrientDef("Vitamin A (RAE)", "mcg", "320", 700, "EFSA PRI, ~midpoint of M750/F650"),
    "retinol": NutrientDef("Retinol", "mcg", "319", 700, "same DRV as vitamin_a (retinol is its dominant form)"),
    "beta_carotene": NutrientDef("Beta-carotene", "mcg", "321", 0, "no independent DRV — contributes to vitamin_a"),
    "vitamin_d": NutrientDef("Vitamin D", "mcg", "328", 10, "UK RNI"),
    "vitamin_e": NutrientDef("Vitamin E", "mg", "323", 15, "US RDA/AI — no UK RNI or EFSA PRI set"),
    "vitamin_k1": NutrientDef("Vitamin K1 (phylloquinone)", "mcg", "430", 70, "EFSA AI"),
    "vitamin_k2": NutrientDef("Vitamin K2 (menaquinone-4)", "mcg", "428", 0, "no independent DRV — contributes to vitamin_k1's role"),
    # --- water-soluble vitamins ---
    "vitamin_c": NutrientDef("Vitamin C", "mg", "401", 40, "UK RNI"),
    "thiamin": NutrientDef("Thiamin (B1)", "mg", "404", 0.9, "UK RNI, midpoint of 0.8-1.0"),
    "riboflavin": NutrientDef("Riboflavin (B2)", "mg", "405", 1.2, "UK RNI, midpoint of 1.1-1.3"),
    "niacin": NutrientDef("Niacin (B3)", "mg", "406", 14, "UK RNI, midpoint of 12-16"),
    "pantothenic_acid": NutrientDef("Pantothenic acid (B5)", "mg", "410", 5, "US RDA/AI — no UK RNI or EFSA PRI set"),
    "vitamin_b6": NutrientDef("Vitamin B6", "mg", "415", 1.3, "UK RNI, midpoint of 1.2-1.4"),
    "biotin": NutrientDef("Biotin (B7)", "mcg", "416", 30, "US RDA/AI — no UK RNI or EFSA PRI set"),
    "folate": NutrientDef("Folate (DFE)", "mcg", "435", 200, "UK RNI"),
    "vitamin_b12": NutrientDef("Vitamin B12", "mcg", "418", 1.5, "UK RNI"),
    "choline": NutrientDef("Choline", "mg", "421", 400, "approx. EFSA AI"),
    # --- minerals ---
    "calcium": NutrientDef("Calcium", "mg", "301", 700, "UK RNI"),
    "iron": NutrientDef("Iron", "mg", "303", 14.8, "UK RNI, premenopausal female figure (higher of the 8.7-14.8 range)"),
    "iron_heme": NutrientDef("Iron, haem", "mg", "364", 0, "no independent DRV — subset of iron"),
    "iron_non_heme": NutrientDef("Iron, non-haem", "mg", "365", 0, "no independent DRV — subset of iron"),
    "magnesium": NutrientDef("Magnesium", "mg", "304", 300, "UK RNI, midpoint of 270-400"),
    "phosphorus": NutrientDef("Phosphorus", "mg", "305", 550, "UK RNI"),
    "potassium": NutrientDef("Potassium", "mg", "306", 3500, "UK RNI"),
    "zinc": NutrientDef("Zinc", "mg", "309", 9.5, "UK RNI, midpoint of 7-11"),
    "copper": NutrientDef("Copper", "mg", "312", 1.5, "EFSA PRI, midpoint of 1.5-1.6 — no UK RNI"),
    "manganese": NutrientDef("Manganese", "mg", "315", 2.0, "US RDA/AI, midpoint of 1.8-2.3 — no UK RNI or EFSA PRI"),
    "selenium": NutrientDef("Selenium", "mcg", "317", 75, "UK RNI"),
    "iodine": NutrientDef("Iodine", "mcg", "314", 140, "UK RNI"),
    # --- dietary fibre ---
    # "Fiber, total dietary" (nbr 291) used rather than the newer AOAC 2011.25
    # method (nbr 293) — 291 is the one present in both Foundation Foods and
    # SR Legacy, avoiding the ambiguity of two methods for the same food.
    "fiber_total": NutrientDef("Fibre, total", "g", "291", 30, "UK SACN/NHS recommendation (30g/day)"),
    "fiber_soluble": NutrientDef("Fibre, soluble", "g", "295", 0, "no independent DRV — subset of fiber_total"),
    "fiber_insoluble": NutrientDef("Fibre, insoluble", "g", "297", 0, "no independent DRV — subset of fiber_total"),
    "resistant_starch": NutrientDef("Resistant starch", "g", "283", 0, "prebiotic fibre — no established DRV"),
    "inulin": NutrientDef("Inulin", "g", "806", 0, "prebiotic fibre — no established DRV"),
    "beta_glucan": NutrientDef("Beta-glucan", "g", "276", 0, "prebiotic fibre — no established DRV"),
    # --- fats ---
    "fat_total": NutrientDef("Total fat", "g", "204", 70, "UK population reference (~33% food energy, adult)"),
    "saturated_fat": NutrientDef("Saturated fat", "g", "606", 30, "UK SACN recommendation (<30g/day average adult)"),
    "monounsaturated_fat": NutrientDef("Monounsaturated fat", "g", "645", 0, "no established individual DRV"),
    "polyunsaturated_fat": NutrientDef("Polyunsaturated fat", "g", "646", 0, "no established individual DRV"),
    # omega-3
    "ala": NutrientDef("ALA (18:3 n-3)", "g", "851", 2.0, "EFSA AI, ~2g/day adult"),
    "epa": NutrientDef("EPA (20:5 n-3)", "g", "629", 0, "no individual DRV — EFSA/WHO guidance is a combined "
                        "EPA+DHA target (~250-500mg/day), not split per acid"),
    "dha": NutrientDef("DHA (22:6 n-3)", "g", "621", 0, "no individual DRV — see epa's note on the combined target"),
    # omega-6
    "la": NutrientDef("LA (18:2 n-6)", "g", "675", 10.0, "EFSA AI, ~10g/day adult"),
    # nutrient_nbr for this one differs by FDC release: 855 in Foundation
    # Foods 2026-04-30, 853 in SR Legacy 2018-04 — both verified directly
    # against nutrient.csv; ingest_fdc.py maps both to this key.
    "arachidonic_acid": NutrientDef("Arachidonic acid (20:4 n-6)", "g", "855", 0, "no established DRV"),
}

# nutrients with no independent DRV (their intake matters, but %DRV gap
# analysis isn't meaningful for them individually)
NO_DRV = {key for key, d in NUTRIENTS.items() if d.adult_drv == 0}
