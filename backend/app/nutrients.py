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

# What kind of claim a nutrient's primary DRV figure is making — read by
# nutrient_targets.py (the nutrient-gap recommendation feature) to decide
# what "meeting the target" even means for a given nutrient. Added
# alongside the existing `drv`/`upper_limit` data rather than as a
# separate table, per "do not create duplicate sources of nutritional
# truth" — this module stays the one place nutrient reference data lives.
#   "minimum_or_adequate_intake" — the ordinary case: an RNI/AI-style
#       figure you want to *reach* (most vitamins/minerals here).
#   "maximum_guideline" — the figure itself is a population ceiling, not a
#       floor (saturated fat, sodium) — this app's %DRV/"reach 100%"
#       framing would be backwards applied to these, so they're excluded
#       from ordinary gap analysis and only ever compared against as an
#       upper bound.
#   "personalized" — energy/protein: a calculation (BMR×activity,
#       bodyweight×activity), not a table lookup; `drv` is unused for these.
#   "informational" — no independent optimisation target at all (a subset
#       of another tracked nutrient, or no established DRV/guideline of any
#       kind) — see `optimisation_eligible`.
TARGET_TYPE_MINIMUM_OR_ADEQUATE_INTAKE = "minimum_or_adequate_intake"
TARGET_TYPE_MAXIMUM_GUIDELINE = "maximum_guideline"
TARGET_TYPE_PERSONALIZED = "personalized"
TARGET_TYPE_INFORMATIONAL = "informational"


@dataclass
class NutrientDef:
    name: str
    unit: str  # "mg", "mcg", or "g", as stored (amount_per_100g uses this unit)
    fdc_nutrient_nbr: str
    drv: dict[str, float] = field(default_factory=dict)  # adult_male/adult_female/pregnant/lactating
    drv_source: str = ""
    # "live_confirmed": at least one figure here (a base value or an
    # increment) was independently checked against a live/primary source
    # this session, per drv_source's text — not just this codebase's
    # opinion of itself, an explicit flag set only where the comment says
    # so. "secondary_source": the default — sourced from the named table
    # (RNI/PRI/RDA) via a secondary comparison table, consistently
    # reproduced across sources but not independently re-verified against
    # the primary document page-by-page. See nutrients.py's module
    # docstring for the fuller caveat this tag is a structured version of.
    drv_confidence: str = "secondary_source"
    # what kind of claim `drv` (or, for "personalized", the calculated
    # figure computed elsewhere) is making — see the TARGET_TYPE_* comment
    # above. Defaults to the ordinary case so every existing entry below
    # didn't need updating individually.
    target_type: str = TARGET_TYPE_MINIMUM_OR_ADEQUATE_INTAKE
    # a tolerable upper intake level, same adult_male/adult_female/
    # pregnant/lactating shape as `drv` — None (not a fabricated number)
    # wherever no figure is confidently known, which is most nutrients
    # here. These are commonly-cited population-level figures (EFSA/US
    # IOM/UK COMA-derived, "secondary_source" confidence unless noted
    # otherwise) for context, NOT medical advice — individual tolerance
    # varies, some published ULs apply only to a specific chemical form or
    # to supplemental/fortified intake rather than ordinary food (noted
    # per-nutrient below where that distinction matters), and some bodies
    # disagree with each other by a factor of 2 or more (also noted). See
    # nutrient_targets.py for how this is actually used/framed to a user —
    # never as a diagnosis, always as "above the upper reference range."
    upper_limit: dict[str, float] | None = None
    upper_limit_source: str | None = None
    upper_limit_confidence: str | None = None
    # False for a nutrient this app has no independent optimisation target
    # for at all (a subset of another tracked nutrient, e.g. iron_heme of
    # iron; or nothing established in any direction) — the recommendation
    # engine (nutrient_gap_analysis.py) must never treat these as a
    # shortfall/excess to optimise toward, only ever informational.
    optimisation_eligible: bool = True
    ineligibility_reason: str | None = None


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
    # --- energy ---
    # No flat DRV here — unlike vitamins/minerals, energy needs are
    # individualized (weight, height, age, sex, activity), not a per-sex/
    # life-stage table lookup. energy.py computes a personalized daily
    # target (Mifflin-St Jeor BMR x activity multiplier); the diary
    # endpoint uses that instead of resolve_drv() for this key specifically.
    "energy": NutrientDef(
        "Energy", "kcal", "208", _drv(0, 0), "no flat DRV — see energy.py",
        target_type=TARGET_TYPE_PERSONALIZED,
    ),
    # No flat DRV here either — same reasoning as energy above. Personalized
    # by bodyweight and activity level (protein_requirement.py); the diary
    # and recipe endpoints use that instead of resolve_drv() for this key.
    "protein": NutrientDef(
        "Protein", "g", "203", _drv(0, 0), "no flat DRV — see protein_requirement.py",
        target_type=TARGET_TYPE_PERSONALIZED,
    ),
    # --- fat-soluble vitamins ---
    "vitamin_a": NutrientDef(
        "Vitamin A (RAE)", "mcg", "320",
        _drv(700, 600, pregnant=700, lactating=950),
        "UK RNI; pregnancy (+100mcg to 700) confirmed live this session; lactation figure "
        "(950) recalled from COMA-derived sources, not re-confirmed",
        drv_confidence="live_confirmed",
        # UL concerns *preformed* vitamin A specifically — this "vitamin_a"
        # key is RAE (retinol activity equivalents, which also folds in
        # carotenoid conversion), so a diet very high in carotenoid-rich
        # vegetables (inefficient conversion, no toxicity link) could show
        # as "above upper limit" here without real risk; retinol's own
        # entry below is the more precise one for actual toxicity concern.
        # Pregnancy: preformed vitamin A carries a well-known teratogenicity
        # concern independent of this numeric figure — treated as a
        # sensitive-context case (conservative handling, not a numeric
        # override) by the recommendation engine, not by inventing a
        # separate pregnancy-specific UL number here.
        upper_limit=_drv(3000, 3000),
        upper_limit_source="commonly-cited EFSA/US IOM preformed-vitamin-A UL for adults",
        upper_limit_confidence="secondary_source",
    ),
    "retinol": NutrientDef(
        "Retinol", "mcg", "319", _drv(700, 600, pregnant=700, lactating=950),
        "same DRV as vitamin_a (retinol is its dominant form)",
        drv_confidence="live_confirmed",
        upper_limit=_drv(3000, 3000),
        upper_limit_source="commonly-cited EFSA/US IOM UL for preformed vitamin A (adults); "
        "same pregnancy caveat as vitamin_a — treat pregnancy conservatively regardless of this figure",
        upper_limit_confidence="secondary_source",
    ),
    "beta_carotene": NutrientDef(
        "Beta-carotene", "mcg", "321", _drv(0, 0), "no independent DRV — contributes to vitamin_a",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — contributes to vitamin_a",
    ),
    "vitamin_d": NutrientDef(
        "Vitamin D", "mcg", "328", _drv(10, 10, pregnant=10, lactating=10),
        "UK RNI — flat 10mcg for all adults since SACN's 2016 update, no pregnancy/lactation increment",
        upper_limit=_drv(100, 100),
        upper_limit_source="commonly-cited EFSA/US IOM UL (100mcg / 4000 IU per day)",
        upper_limit_confidence="secondary_source",
    ),
    "vitamin_e": NutrientDef(
        "Vitamin E", "mg", "323", _drv(15, 15, pregnant=15, lactating=19),
        "US RDA/AI — no UK RNI or EFSA PRI set; lactation figure (19) is the US AI increment",
        upper_limit=_drv(300, 300),
        upper_limit_source="commonly-cited EFSA UL (alpha-tocopherol form)",
        upper_limit_confidence="secondary_source",
    ),
    "vitamin_k1": NutrientDef("Vitamin K1 (phylloquinone)", "mcg", "430", _drv(70, 70), "EFSA AI, no confirmed pregnancy/lactation increment"),
    "vitamin_k2": NutrientDef(
        "Vitamin K2 (menaquinone-4)", "mcg", "428", _drv(0, 0), "no independent DRV — contributes to vitamin_k1's role",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — contributes to vitamin_k1's role",
    ),
    # --- water-soluble vitamins ---
    "vitamin_c": NutrientDef(
        "Vitamin C", "mg", "401", _drv(40, 40, pregnant=50, lactating=70),
        "UK RNI; pregnancy/lactation increments are commonly-cited COMA figures, moderate confidence",
        # rarely approachable from food alone — included for completeness,
        # not because it's a practically binding constraint
        upper_limit=_drv(2000, 2000),
        upper_limit_source="commonly-cited US IOM UL (GI-upset threshold)",
        upper_limit_confidence="secondary_source",
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
    # No UL set: the established UL (~900mg) specifically concerns
    # supplemental *nicotinic acid* (flushing) — ordinary food-derived
    # niacin (which this app tracks) has no meaningful excess risk at
    # realistic dietary intakes, so applying that figure here would imply
    # a risk this app has no basis to actually flag from food alone.
    "niacin": NutrientDef(
        "Niacin (B3)", "mg", "406", _drv(16, 12),
        "UK RNI, no confirmed pregnancy/lactation increment — COMA ties niacin to energy intake "
        "rather than a fixed increment, so adult_female is used as-is",
    ),
    "pantothenic_acid": NutrientDef(
        "Pantothenic acid (B5)", "mg", "410", _drv(5, 5, lactating=7),
        "US RDA/AI — no UK RNI or EFSA PRI set; lactation figure (7) is the US AI increment",
    ),
    # No UL set: EFSA's 2023 re-evaluation substantially lowered its
    # figure from long-standing prior guidance, and this module can't
    # verify which figure currently stands without a live source — rather
    # than cite a number that may already be outdated, none is given.
    "vitamin_b6": NutrientDef(
        "Vitamin B6", "mg", "415", _drv(1.4, 1.2),
        "UK RNI, no confirmed pregnancy/lactation increment",
    ),
    "biotin": NutrientDef("Biotin (B7)", "mcg", "416", _drv(30, 30), "US RDA/AI — no UK RNI or EFSA PRI set, no confirmed increment"),
    # No UL set: the established UL concerns *synthetic folic acid*
    # (fortification/supplements) specifically, masking vitamin B12
    # deficiency symptoms — this app's "folate" figure is DFE (natural
    # food folate + synthetic, combined), and natural food folate itself
    # has no established toxicity/UL. Applying the synthetic-only figure
    # to a combined DFE total would overstate risk for anyone eating
    # folate-rich food rather than taking a supplement.
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
        upper_limit=_drv(3500, 3500),
        upper_limit_source="US IOM UL — EFSA has not set an equivalent figure",
        upper_limit_confidence="secondary_source",
    ),
    # --- minerals ---
    "calcium": NutrientDef(
        "Calcium", "mg", "301", _drv(700, 700, pregnant=700, lactating=1250),
        "UK RNI; no pregnancy increment and +550mg lactation increment both confirmed live this session",
        drv_confidence="live_confirmed",
        upper_limit=_drv(2500, 2500),
        upper_limit_source="commonly-cited EFSA/US IOM UL",
        upper_limit_confidence="secondary_source",
    ),
    "iron": NutrientDef(
        "Iron", "mg", "303", _drv(8.7, 14.8, pregnant=14.8, lactating=14.8),
        "UK RNI; no pregnancy increment confirmed live this session (UK position: absorption "
        "efficiency rises to meet demand). Lactation also left at the female baseline — no "
        "confirmed UK increment found",
        drv_confidence="live_confirmed",
        upper_limit=_drv(45, 45),
        upper_limit_source="commonly-cited US IOM UL (combined dietary+supplemental; GI-distress threshold)",
        upper_limit_confidence="secondary_source",
    ),
    "iron_heme": NutrientDef(
        "Iron, haem", "mg", "364", _drv(0, 0), "no independent DRV — subset of iron",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — subset of iron",
    ),
    "iron_non_heme": NutrientDef(
        "Iron, non-haem", "mg", "365", _drv(0, 0), "no independent DRV — subset of iron",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — subset of iron",
    ),
    "magnesium": NutrientDef(
        "Magnesium", "mg", "304", _drv(300, 270),
        "UK RNI, no confirmed pregnancy/lactation increment",
        # No UL set: the established UL (~350mg) concerns *supplemental*
        # magnesium specifically (osmotic diarrhoea) — food-derived
        # magnesium has no established UL (excess is renally cleared).
    ),
    "phosphorus": NutrientDef(
        "Phosphorus", "mg", "305", _drv(550, 550), "UK RNI, flat across groups",
        # No UL set: general-population risk from food alone is low; the
        # figures in circulation are most relevant to impaired renal
        # clearance, which this app has no way to assess (see prompt 11's
        # "sensitive contexts" handling — flagged qualitatively there, not
        # with a numeric UL this module isn't confident applies generally).
    ),
    "potassium": NutrientDef(
        "Potassium", "mg", "306", _drv(3500, 3500), "UK RNI, flat across groups",
        # No UL set for the same reason as phosphorus: excess potassium
        # risk is specifically a renal-impairment concern, not a general-
        # population one — this app has no renal-function data to condition
        # on, so no UL is asserted rather than implying a general-population
        # risk that isn't the real basis for caution here.
    ),
    # nutrient_nbr 307 is the standard/stable USDA FDC number for "Sodium, Na"
    # (unlike arachidonic_acid's, this one has never been seen to vary between
    # datasets) — not independently re-verified against a live nutrient.csv
    # this session, flagged per this module's own house rule on that.
    #
    # No upward drv here deliberately — sodium is a "don't exceed" nutrient,
    # not a "reach this" one, and this app's percent_drv/gap-analysis
    # machinery is built entirely around targets you want to *reach*.
    # Applying it to sodium would tell a user who already eats too much salt
    # to "eat more to hit 100%" — exactly backwards. See food_chemistry.py
    # for the sodium:potassium ratio, which handles the inverted framing
    # honestly instead of forcing it through resolve_drv(). The
    # nutrient-gap recommendation engine (nutrient_targets.py) reads
    # `upper_limit` for this one instead of `drv` for exactly that reason.
    "sodium": NutrientDef(
        "Sodium", "mg", "307", _drv(0, 0), "no upward DRV — see food_chemistry.py for the sodium:potassium ratio",
        target_type=TARGET_TYPE_MAXIMUM_GUIDELINE,
        upper_limit=_drv(2400, 2400),
        upper_limit_source="UK SACN/NHS population salt-reduction target (6g salt/day = 2400mg sodium)",
        upper_limit_confidence="secondary_source",
    ),
    "zinc": NutrientDef(
        "Zinc", "mg", "309", _drv(9.5, 7.0, lactating=13.0),
        "UK RNI; lactation increment (to 13, first 4 months) is a commonly-cited COMA figure, "
        "no confirmed pregnancy increment",
        upper_limit=_drv(25, 25),
        upper_limit_source="EFSA UL — more conservative than the US IOM's 40mg figure; bodies disagree, EFSA's used here",
        upper_limit_confidence="secondary_source",
    ),
    "copper": NutrientDef(
        "Copper", "mg", "312", _drv(1.5, 1.5), "EFSA PRI — no UK RNI, no confirmed sex/life-stage split",
        upper_limit=_drv(5, 5),
        upper_limit_source="commonly-cited EFSA UL",
        upper_limit_confidence="secondary_source",
    ),
    "manganese": NutrientDef(
        "Manganese", "mg", "315", _drv(2.0, 2.0), "US RDA/AI — no UK RNI or EFSA PRI, no confirmed split",
        # No UL set: EFSA concluded available data were insufficient to set
        # one; the older US figure isn't corroborated elsewhere, so none is
        # asserted here rather than picking the one body that has a number.
    ),
    "selenium": NutrientDef(
        "Selenium", "mcg", "317", _drv(75, 60, lactating=75),
        "UK RNI; lactation increment (+15) is a commonly-cited COMA figure, no confirmed "
        "pregnancy increment",
        upper_limit=_drv(300, 300),
        upper_limit_source="commonly-cited EFSA UL",
        upper_limit_confidence="secondary_source",
    ),
    "iodine": NutrientDef(
        "Iodine", "mcg", "314", _drv(140, 140),
        "UK RNI, flat across groups — UK (unlike WHO) sets no pregnancy/lactation increment",
        upper_limit=_drv(600, 600),
        upper_limit_source="EFSA UL — more conservative than the US IOM's 1100mcg figure; bodies disagree, "
        "EFSA's used here given thyroid-function risk from excess",
        upper_limit_confidence="secondary_source",
    ),
    # --- dietary fibre ---
    # "Fiber, total dietary" (nbr 291) used rather than the newer AOAC 2011.25
    # method (nbr 293) — 291 is the one present in both Foundation Foods and
    # SR Legacy, avoiding the ambiguity of two methods for the same food.
    "fiber_total": NutrientDef(
        "Fibre, total", "g", "291", _drv(30, 30),
        "UK SACN/NHS recommendation (30g/day), flat across groups",
    ),
    "fiber_soluble": NutrientDef(
        "Fibre, soluble", "g", "295", _drv(0, 0), "no independent DRV — subset of fiber_total",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — subset of fiber_total",
    ),
    "fiber_insoluble": NutrientDef(
        "Fibre, insoluble", "g", "297", _drv(0, 0), "no independent DRV — subset of fiber_total",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no independent DRV — subset of fiber_total",
    ),
    "resistant_starch": NutrientDef(
        "Resistant starch", "g", "283", _drv(0, 0), "prebiotic fibre — no established DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="prebiotic fibre — no established DRV",
    ),
    "inulin": NutrientDef(
        "Inulin", "g", "806", _drv(0, 0), "prebiotic fibre — no established DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="prebiotic fibre — no established DRV",
    ),
    "beta_glucan": NutrientDef(
        "Beta-glucan", "g", "276", _drv(0, 0), "prebiotic fibre — no established DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="prebiotic fibre — no established DRV",
    ),
    # --- fats ---
    "fat_total": NutrientDef("Total fat", "g", "204", _drv(95, 70), "UK population reference (~33% food energy)"),
    # Reclassified as a ceiling, not a floor, for the recommendation engine
    # (prompt 2) — the existing 30/30 figure is a "no more than" population
    # guideline (UK SACN), and this app's ordinary %DRV/"reach 100%" framing
    # would be backwards applied to it, same reasoning as sodium above. The
    # number itself is unchanged (still read via `drv`/resolve_drv() for
    # any existing caller), only how the NEW module interprets it changes.
    "saturated_fat": NutrientDef(
        "Saturated fat", "g", "606", _drv(30, 30), "UK SACN recommendation (<30g/day average adult)",
        target_type=TARGET_TYPE_MAXIMUM_GUIDELINE,
    ),
    "monounsaturated_fat": NutrientDef(
        "Monounsaturated fat", "g", "645", _drv(0, 0), "no established individual DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no established individual DRV",
    ),
    "polyunsaturated_fat": NutrientDef(
        "Polyunsaturated fat", "g", "646", _drv(0, 0), "no established individual DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no established individual DRV",
    ),
    # omega-3
    "ala": NutrientDef("ALA (18:3 n-3)", "g", "851", _drv(2.0, 2.0), "EFSA AI, ~2g/day, no confirmed sex split"),
    "epa": NutrientDef(
        "EPA (20:5 n-3)", "g", "629", _drv(0, 0),
        "no individual DRV — EFSA/WHO guidance is a combined EPA+DHA target (~250-500mg/day), not split per acid",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no individual DRV — part of a combined EPA+DHA target, not split per acid",
    ),
    "dha": NutrientDef(
        "DHA (22:6 n-3)", "g", "621", _drv(0, 0), "no individual DRV — see epa's note on the combined target",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no individual DRV — part of a combined EPA+DHA target, not split per acid",
    ),
    # omega-6
    "la": NutrientDef("LA (18:2 n-6)", "g", "675", _drv(10.0, 10.0), "EFSA AI, ~10g/day, no confirmed sex split"),
    # nutrient_nbr for this one differs by FDC release: 855 in Foundation
    # Foods 2026-04-30, 853 in SR Legacy 2018-04 — both verified directly
    # against nutrient.csv; ingest_fdc.py maps both to this key.
    "arachidonic_acid": NutrientDef(
        "Arachidonic acid (20:4 n-6)", "g", "855", _drv(0, 0), "no established DRV",
        target_type=TARGET_TYPE_INFORMATIONAL, optimisation_eligible=False,
        ineligibility_reason="no established DRV",
    ),
}

# nutrients with no independent DRV in any variant (their intake matters,
# but %DRV gap analysis isn't meaningful for them individually)
NO_DRV = {key for key, d in NUTRIENTS.items() if not any(d.drv.values())}


def _drv_variant(profile: DRVProfile | None) -> str:
    """Which column of a `drv`/`upper_limit`-shaped dict applies to this
    profile — shared by resolve_drv and resolve_upper_limit so the two
    can never disagree about whose figure a given profile gets."""
    if profile is None:
        return "adult_female"
    sex, is_pregnant, is_lactating = profile
    if is_lactating:
        return "lactating"
    if is_pregnant:
        return "pregnant"
    if sex == "male":
        return "adult_male"
    return "adult_female"


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
    value = nutrient_def.drv.get(_drv_variant(profile), 0)
    return value or None


def resolve_upper_limit(nutrient_key: str, profile: DRVProfile | None = None) -> float | None:
    """Look up a nutrient's tolerable upper limit / maximum guideline
    ceiling for a given profile — same profile semantics as resolve_drv.
    None wherever `NutrientDef.upper_limit` isn't set at all (most
    nutrients here), never a fabricated figure. See NutrientDef's
    docstring for what these figures do and don't mean."""
    nutrient_def = NUTRIENTS.get(nutrient_key)
    if nutrient_def is None or not nutrient_def.upper_limit:
        return None
    value = nutrient_def.upper_limit.get(_drv_variant(profile), 0)
    return value or None
