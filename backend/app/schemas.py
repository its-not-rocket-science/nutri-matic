from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .data_quality import implausibility_reason
from .methodology import DRV_METHODOLOGY_VERSION
from .nutrients import NutrientDef

Sex = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
Meal = Literal["breakfast", "lunch", "dinner", "snack"]


class AminoAcidProfile(BaseModel):
    histidine: float | None = None
    isoleucine: float | None = None
    leucine: float | None = None
    lysine: float | None = None
    met_cys: float | None = Field(default=None, description="methionine + cysteine")
    phe_tyr: float | None = Field(default=None, description="phenylalanine + tyrosine")
    threonine: float | None = None
    tryptophan: float | None = None
    valine: float | None = None


class FoodCreate(BaseModel):
    name: str
    protein_g_per_100g: float
    amino_acids: AminoAcidProfile
    digestibility_diaas: AminoAcidProfile | None = None
    digestibility_diaas_source: str | None = None
    digestibility_pdcaas: float | None = None
    digestibility_pdcaas_source: str | None = None
    fdc_id: int | None = None
    data_type: str | None = None
    gtin_upc: str | None = None


class DietaryStatusOut(BaseModel):
    """Display-only — see dietary_filter.py's module docstring. Never
    "excluded": excluded items are dropped before display, not badged."""

    status: Literal["avoid", "unknown"]
    confidence: Literal["high", "low"]
    reasons: list[str]


class FoodOut(FoodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # only set on search/discovery results for a signed-in user with dietary
    # constraints — see dietary_filter.py. Absent (null) elsewhere, not a
    # claim that the food's been checked and is safe.
    dietary_status: DietaryStatusOut | None = None


class FoodListOut(BaseModel):
    items: list[FoodOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class ExcludedIngredientOut(BaseModel):
    food_id: int
    name: str
    protein_g: float


class ScoreOut(BaseModel):
    method: str
    pattern_used: str
    score: float
    limiting_amino_acid: str
    per_aa_ratios: dict[str, float]
    digestibility_source: str | None = None
    # see methodology.SCORING_METHODOLOGY_VERSION — bumps whenever a change
    # to the scoring formula or reference patterns would alter this score
    # for the same input data
    methodology_version: str
    # coverage_fraction < 1.0 / is_partial True means this score was computed
    # from only the ingredients with complete amino acid + digestibility
    # data — see aggregation.compute_protein_quality_with_coverage.
    # excluded_ingredients lists exactly what was left out and how much
    # protein it represents. coverage_fraction is 1.0 and the list is empty
    # whenever every ingredient had complete data.
    coverage_fraction: float = 1.0
    is_partial: bool = False
    excluded_ingredients: list[ExcludedIngredientOut] = []


class RobustnessMetricOut(BaseModel):
    """One metric's Monte Carlo robustness result — see
    stock_recipes/robustness.py. baseline/display_rating/explanation are
    always present when the metric could be calculated at all;
    not_calculated_reason is set (and every numeric field null) when it
    couldn't — never a fabricated rating."""

    baseline: float | None = None
    median: float | None = None
    p10: float | None = None
    p90: float | None = None
    cv: float | None = None
    threshold: float | None = None
    prob_above_threshold: float | None = None
    top_influential: list[dict] = []
    optional_sensitivity: float | None = None
    unmatched_uncertainty_note: str | None = None
    display_rating: int | None = None
    explanation: str = ""
    not_calculated_reason: str | None = None
    # only meaningful for protein_quality_diaas/pdcaas and
    # absorbed_protein_diaas/pdcaas — see
    # aggregation.compute_protein_quality_with_coverage. None/empty for
    # every other metric.
    coverage_fraction: float | None = None
    excluded_foods: list[dict] = []


class RobustnessOut(BaseModel):
    """A stock recipe's current robustness analysis (models.RobustnessResult)
    — describes how stable this recipe's calculated nutrition is under
    plausible ingredient-quantity variation. NOT a health score, a
    suitability judgement, or a claim about the source recipe's own
    reliability — see docs/stock-recipes.md."""

    model_version: str
    computed_at: datetime
    simulation_count: int
    random_seed: int
    metrics: dict[str, RobustnessMetricOut]
    overall_rating: int | None
    overall_explanation: str


class NutrientProvenanceOut(BaseModel):
    key: str
    name: str
    fdc_nutrient_nbr: str
    amount_per_100g: float
    drv_source: str | None
    drv_confidence: str | None
    # see data_quality.implausibility_reason — set when this raw value is
    # thousands of times its own DRV (almost certainly a source data error).
    # Still shown here as-is; excluded from totals/suggestions elsewhere.
    implausible_reason: str | None = None


class FoodProvenanceOut(BaseModel):
    food_id: int
    food_name: str
    fdc_id: int | None
    data_type: str | None
    dataset_label: str | None
    gtin_upc: str | None
    digestibility_diaas_source: str | None
    digestibility_pdcaas_source: str | None
    nutrients: list[NutrientProvenanceOut]


class ComplementSuggestionOut(BaseModel):
    food_id: int
    food_name: str
    # the DIAAS/PDCAAS score of 100g of the subject food + 100g of this
    # suggestion, actually computed — not a guess from raw amino acid content
    combined_score: float
    score_improvement: float


class ComplementOut(BaseModel):
    original_score: float
    limiting_amino_acid: str
    suggestions: list[ComplementSuggestionOut]
    methodology_version: str


class NutrientAmountOut(BaseModel):
    key: str
    name: str
    unit: str
    # per 100g for a food, per serving for a recipe, per day for a diary summary
    amount: float
    adult_drv: float | None
    percent_drv: float | None
    # provenance of adult_drv — see nutrients.NutrientDef.drv_source; null only
    # for nutrients with no DRV at all (adult_drv is also null in that case)
    drv_source: str | None
    # "live_confirmed" | "secondary_source" | null — see nutrients.NutrientDef.drv_confidence
    drv_confidence: str | None
    # see methodology.DRV_METHODOLOGY_VERSION — bumps whenever a change to
    # the DRV matrix or resolve_drv() would alter this figure for the same
    # profile/nutrient
    drv_methodology_version: str
    # see data_quality.implausibility_reason — set when `amount` is thousands
    # of times its own DRV (almost certainly a source data error, e.g. a
    # branded food's manufacturer-submitted value). Still shown as-is; this
    # amount has already been excluded from the total/suggestion it appears
    # in by the caller — the field is purely explanatory.
    implausible_reason: str | None = None
    # True only for the "energy" row when the target reflects a weight-loss
    # goal's calorie deficit (see energy_goal.py) rather than plain
    # maintenance EER — the frontend shows a visible note (not just a
    # tooltip) whenever this is set, so the deficit is never applied silently
    goal_adjusted: bool = False

    @classmethod
    def build(
        cls,
        key: str,
        nutrient_def: NutrientDef,
        amount: float,
        drv: float | None,
        *,
        drv_source: str | None = None,
        drv_confidence: str | None = None,
        goal_adjusted: bool = False,
    ) -> "NutrientAmountOut":
        """Shared shaping logic for the four call sites that turn a
        (nutrient_def, amount, drv) triple into this schema — food/recipe
        nutrients endpoints and the diary day/trends endpoints. Callers with
        a personalized override (currently just diary's/recipes' "energy"
        nutrient, whose source/confidence describe a BMR calculation rather
        than a table lookup) pass drv_source/drv_confidence explicitly;
        everyone else gets them straight from nutrient_def."""
        return cls(
            key=key,
            name=nutrient_def.name,
            unit=nutrient_def.unit,
            amount=amount,
            adult_drv=drv,
            percent_drv=(amount / drv * 100) if drv else None,
            drv_source=drv_source if drv_source is not None else (nutrient_def.drv_source or None),
            drv_confidence=(
                drv_confidence
                if drv_confidence is not None
                else (nutrient_def.drv_confidence if nutrient_def.drv_source else None)
            ),
            drv_methodology_version=DRV_METHODOLOGY_VERSION,
            implausible_reason=implausibility_reason(key, amount),
            goal_adjusted=goal_adjusted,
        )


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def email_must_look_like_email(cls, v: str) -> str:
        # Deliberately not pulling in the `email-validator` package for full
        # RFC validation — this app has no email-sending feature (no
        # verification link, no password reset) to make deep validation
        # worth the dependency; this just blocks the obviously-not-an-email
        # inputs (empty string, no "@") that register() would otherwise
        # cheerfully hash a password for and store.
        if "@" not in v or v.startswith("@") or v.endswith("@"):
            raise ValueError("must be a valid email address")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Account-level fields only — sex/birth_year/weight/dietary_pattern/
    goal etc. moved to ProfileOut with the household-profiles feature (an
    account can have more than one Profile, so they no longer belong here).
    See routers/profiles.py."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    # ISO 4217 code, or null to use the browser locale's implied currency
    currency: str | None = None
    # entitlement primitive (Phase 3) — see entitlements.py. Not editable
    # via AccountUpdate: plan changes go through a future billing/admin
    # flow, never self-service.
    plan: str = "free"


class AccountUpdate(BaseModel):
    currency: str | None = None


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    is_account_owner: bool
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False
    weight_kg: float | None = None
    height_cm: float | None = None
    dietary_pattern: str | None = None
    # onboarding's step-1 pick — null if never set (skipped onboarding, or a
    # pre-this-feature account)
    goal: str | None = None


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1)
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False
    weight_kg: float | None = None
    height_cm: float | None = None
    dietary_pattern: str | None = None
    goal: str | None = None


class EntitlementsOut(BaseModel):
    plan: str
    effective_plan: str
    plan_expires_at: datetime | None = None


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1)
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False
    weight_kg: float | None = None
    height_cm: float | None = None
    dietary_pattern: str | None = None
    goal: str | None = None


class DietaryConstraintCreate(BaseModel):
    # "allergy" | "intolerance" | "religious" | "medical" | "preference"
    category: str
    # a dietary_tags.TAGS/RELIGIOUS_REQUIREMENTS key; null for medical rows
    # and free-text preferences, which are informational-only (see
    # models.DietaryConstraint's docstring for why those aren't enforced)
    tag: str | None = None
    # "hard_exclude" | "avoid"; null for medical/free-text rows
    severity: str | None = None
    note: str | None = None


class DietaryConstraintOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    tag: str | None
    severity: str | None
    note: str | None


class DietaryTagOut(BaseModel):
    key: str
    label: str


class DietaryPatternOut(BaseModel):
    key: str
    label: str
    excludes: list[str]


class DietaryVocabularyOut(BaseModel):
    """The full controlled vocabulary (dietary_tags.py), so the frontend
    never hardcodes tag keys/labels — a new tag added there shows up here
    automatically."""

    allergen_tags: list[DietaryTagOut]
    religious_requirements: list[DietaryPatternOut]
    dietary_patterns: list[DietaryPatternOut]


class RecipeIngredientCreate(BaseModel):
    food_id: int
    quantity_g: float


class RecipeCreate(BaseModel):
    name: str
    servings: float
    ingredients: list[RecipeIngredientCreate]
    source_url: str | None = None
    method: str | None = None


class RecipeUpdate(BaseModel):
    name: str | None = None
    servings: float | None = None
    source_url: str | None = None
    method: str | None = None


class RecipeIngredientAdd(BaseModel):
    food_id: int
    quantity_g: float


class RecipeIngredientUpdate(BaseModel):
    quantity_g: float


class RecipeIngredientProvenanceOut(BaseModel):
    """Only present for a stock-recipe ingredient imported via
    stock_recipes/ — null on RecipeIngredientOut for an ordinary
    user-added ingredient, which has no underlying
    models.RecipeIngredientProvenance row at all.

    Exposes the alias/proxy confidence distinction prompt sections 6/8 ask
    for — which relationship food_matching.py's match was
    ("exact"/"regional_equivalent"/"close_analogue"/"category_proxy"/
    "reviewed_substitution" — see ingredient_aliases.AliasRelationship),
    how confident that tier is, the human-readable rationale behind it,
    and (for a reviewed/preferred-id match) whether resolution actually
    had to fall back to a description search — so a user or developer can
    tell an exact match apart from a reviewed approximation, and know when
    a substitution's target validation is worth a second look. Purely
    informational: nothing here is read by aggregation.py, so it can never
    affect a nutrition calculation."""

    model_config = ConfigDict(from_attributes=True)
    match_method: str | None
    match_confidence: float | None
    match_relationship: str | None
    match_rationale: str | None = None
    match_preferred_fdc_id: int | None = None
    match_preferred_food_id: int | None = None
    match_used_fallback: bool | None = None
    match_validation_warning: str | None = None


class RecipeIngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    food_id: int
    food_name: str
    quantity_g: float
    provenance: RecipeIngredientProvenanceOut | None = None


class RecipeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    servings: float
    ingredients: list[RecipeIngredientOut]
    owner_email: str
    is_owner: bool
    is_public: bool
    average_rating: float | None
    rating_count: int
    tags: list[str]
    # only set on recipe search/discovery results for a signed-in user with
    # dietary constraints — see dietary_filter.py. Worst status across the
    # recipe's ingredients; absent (null) elsewhere.
    dietary_status: DietaryStatusOut | None = None
    # both optional — see models.Recipe
    source_url: str | None = None
    method: str | None = None
    # curated-stock-library fields (stock_recipes/) — all null/false for an
    # ordinary user-created recipe, which never touches these.
    # True only for a recipe owned by the is_system account — distinct from
    # is_public, which a community "share" feature could someday also set.
    is_stock: bool = False
    source_name: str | None = None
    match_coverage_lines: float | None = None
    match_coverage_mass: float | None = None
    # raw ingredient lines the importer couldn't match to a food — shown as
    # a data-quality warning; empty for a non-stock recipe.
    unresolved_ingredients: list[str] = []
    # set only for a stock recipe whose ingredient list was deliberately
    # adapted/composited for nutritional-analysis purposes rather than
    # transcribed as a specific real-world dish (e.g. a generic "muesli"
    # stand-in built from rolled oats/dried fruit/nuts/seeds) — see prompt
    # section 6/7. The frontend surfaces this as its own provenance
    # category, distinct from both a structured-data import and an
    # ordinary manually-curated recipe, so it's never presented as if
    # scraped or transcribed verbatim from source_url.
    educational_note: str | None = None


class RecipeShareCreate(BaseModel):
    email: str


class RecipeShareOut(BaseModel):
    id: int
    email: str
    created_at: datetime


class RecipeRatingCreate(BaseModel):
    rating: int = Field(ge=1, le=5)


class RecipeRatingSummary(BaseModel):
    average: float | None
    count: int
    my_rating: int | None


class RecipeCommentCreate(BaseModel):
    body: str


class RecipeCommentOut(BaseModel):
    id: int
    user_email: str
    body: str
    created_at: datetime
    is_own: bool


class TagAdd(BaseModel):
    tag: str


class CollectionCreate(BaseModel):
    name: str


class CollectionOut(BaseModel):
    id: int
    name: str
    recipe_count: int
    owner_email: str
    is_owner: bool
    is_public: bool
    is_stock: bool = False


class CollectionDetailOut(BaseModel):
    id: int
    name: str
    owner_email: str
    is_owner: bool
    is_public: bool
    is_stock: bool = False
    recipes: list[RecipeOut]


class CollectionRecipeAdd(BaseModel):
    recipe_id: int


class DiaryEntryCreate(BaseModel):
    entry_date: date
    meal: Meal
    food_id: int | None = None
    quantity_g: float | None = None
    recipe_id: int | None = None
    quantity_servings: float | None = None

    @model_validator(mode="after")
    def _exactly_one_of_food_or_recipe(self):
        is_food = self.food_id is not None and self.quantity_g is not None
        is_recipe = self.recipe_id is not None and self.quantity_servings is not None
        if is_food == is_recipe:  # both or neither
            raise ValueError(
                "Provide exactly one of (food_id, quantity_g) or (recipe_id, quantity_servings)"
            )
        return self


class DiaryEntryOut(BaseModel):
    id: int
    entry_date: date
    meal: Meal
    food_id: int | None
    food_name: str | None
    quantity_g: float | None
    recipe_id: int | None
    recipe_name: str | None
    quantity_servings: float | None


class MealIronBioavailabilityOut(BaseModel):
    meal: Meal
    heme_iron_mg: float
    non_heme_iron_mg: float
    vitamin_c_mg: float
    absorbed_heme_mg: float
    absorbed_non_heme_mg: float
    absorbed_total_mg: float
    non_heme_absorption_tier: Literal["baseline", "enhanced"]
    iron_split_source: Literal["measured", "estimated"]


class CalciumPhosphorusOut(BaseModel):
    calcium_mg: float
    phosphorus_mg: float
    ratio: float
    guidance: str


class SodiumPotassiumOut(BaseModel):
    sodium_mg: float
    potassium_mg: float
    ratio: float | None
    guidance: str


class MealProteinDistributionOut(BaseModel):
    meal: Meal
    protein_g: float
    leucine_g: float
    leucine_threshold_g: float
    meets_leucine_threshold: bool


class AbsorbedProteinOut(BaseModel):
    total_protein_g: float
    # null if that method's digestibility data is incomplete for the day's
    # ingredient mix — never a guessed/averaged fallback (see
    # protein_absorption.py)
    diaas_absorbed_g: float | None
    pdcaas_absorbed_g: float | None
    # null if the profile is incomplete (see protein_requirement.py) —
    # weight, birth year, and activity level are all required
    target_g: float | None
    diaas_percent_drv: float | None
    pdcaas_percent_drv: float | None
    # < 1.0 means the corresponding *_absorbed_g was computed from only the
    # ingredients with complete data for that method — null whenever the
    # corresponding *_absorbed_g is itself null (nothing to qualify)
    diaas_coverage_fraction: float | None = None
    pdcaas_coverage_fraction: float | None = None


class QuickAddItemOut(BaseModel):
    food_id: int | None
    food_name: str | None
    recipe_id: int | None
    recipe_name: str | None
    # the quantity used the most recent time this was logged — a reasonable
    # one-click default, not necessarily today's intended amount
    quantity_g: float | None
    quantity_servings: float | None
    last_logged: date
    log_count: int


class QuickAddOut(BaseModel):
    recent: list[QuickAddItemOut]
    frequent: list[QuickAddItemOut]


class DiarySummaryOut(BaseModel):
    entries: list[DiaryEntryOut]
    nutrients: list[NutrientAmountOut]
    iron_bioavailability: list[MealIronBioavailabilityOut]
    calcium_phosphorus: CalciumPhosphorusOut | None
    sodium_potassium: SodiumPotassiumOut | None
    protein_distribution: list[MealProteinDistributionOut]
    absorbed_protein: AbsorbedProteinOut | None


class DiarySnapshotOut(BaseModel):
    """Snapshot Mode's response shape — the frozen summary plus the
    methodology versions in effect when it was taken, so a caller can tell
    at a glance whether today's Live Mode would compute something
    different. See docs/live-vs-snapshot-mode.md."""

    entry_date: date
    drv_methodology_version: str
    scoring_methodology_version: str
    created_at: datetime
    summary: DiarySummaryOut


class FoodNutrientRankOut(BaseModel):
    food_id: int
    food_name: str
    amount_per_100g: float


class GapSuggestionOut(BaseModel):
    nutrient_key: str
    nutrient_name: str
    unit: str
    percent_drv: float
    foods: list[FoodNutrientRankOut]


class OptimizationSuggestionOut(BaseModel):
    action: Literal["add", "swap", "add_recipe"]
    # food_id/quantity_g are null for "add_recipe" (recipe_id/quantity_servings
    # are set instead) — a recipe addition isn't a single food at a gram amount
    food_id: int | None
    food_name: str
    quantity_g: float | None
    replaces_food_id: int | None
    replaces_food_name: str | None
    before_percent_drv: float
    after_percent_drv: float
    improvement: float
    calories_added: float
    improvement_per_100kcal: float | None
    # None when no price is on file for this user for the food(s) involved
    # — never fabricated, never defaulted to 0
    estimated_cost: float | None
    rationale: str
    recipe_id: int | None = None
    quantity_servings: float | None = None


class MealOptimizationOut(BaseModel):
    meal: Meal
    target_nutrient_key: str
    target_nutrient_name: str
    suggestions: list[OptimizationSuggestionOut]


class PlanOptimizationOut(BaseModel):
    """Same idea as MealOptimizationOut but scoped to a whole meal-plan date
    range rather than one day's meal — there's no single `meal` to name, so
    this is a distinct (not reused) response shape."""

    start_date: date
    end_date: date
    target_nutrient_key: str
    target_nutrient_name: str
    suggestions: list[OptimizationSuggestionOut]


class MealPlanEntryCreate(BaseModel):
    plan_date: date
    meal: Meal
    food_id: int | None = None
    quantity_g: float | None = None
    recipe_id: int | None = None
    quantity_servings: float | None = None

    @model_validator(mode="after")
    def _exactly_one_of_food_or_recipe(self):
        is_food = self.food_id is not None and self.quantity_g is not None
        is_recipe = self.recipe_id is not None and self.quantity_servings is not None
        if is_food == is_recipe:  # both or neither
            raise ValueError(
                "Provide exactly one of (food_id, quantity_g) or (recipe_id, quantity_servings)"
            )
        return self


class MealPlanEntryOut(BaseModel):
    id: int
    plan_date: date
    meal: Meal
    food_id: int | None
    food_name: str | None
    quantity_g: float | None
    recipe_id: int | None
    recipe_name: str | None
    quantity_servings: float | None


class FoodPriceCreate(BaseModel):
    package_price: float = Field(gt=0)
    package_quantity_g: float = Field(gt=0)


class FoodPriceOut(BaseModel):
    id: int
    food_id: int
    food_name: str
    package_price: float
    package_quantity_g: float
    price_per_100g: float


class DiaryMealTemplateItemOut(BaseModel):
    food_id: int | None
    food_name: str | None
    quantity_g: float | None
    recipe_id: int | None
    recipe_name: str | None
    quantity_servings: float | None


class DiaryMealTemplateCreate(BaseModel):
    name: str
    entry_date: date
    meal: Meal


class DiaryMealTemplateOut(BaseModel):
    id: int
    name: str
    item_count: int


class DiaryMealTemplateDetailOut(BaseModel):
    id: int
    name: str
    items: list[DiaryMealTemplateItemOut]


class MealPlanTemplateEntryOut(BaseModel):
    day_offset: int = Field(ge=0, le=6)
    meal: Meal
    food_id: int | None
    food_name: str | None
    quantity_g: float | None
    recipe_id: int | None
    recipe_name: str | None
    quantity_servings: float | None


class MealPlanTemplateCreate(BaseModel):
    name: str
    start_date: date
    end_date: date


class MealPlanTemplateOut(BaseModel):
    id: int
    name: str
    entry_count: int


class MealPlanTemplateDetailOut(BaseModel):
    id: int
    name: str
    entries: list[MealPlanTemplateEntryOut]


class ShoppingListItemOut(BaseModel):
    food_id: int
    food_name: str
    quantity_g: float
    price_per_100g: float | None
    estimated_cost: float | None


class ShoppingListOut(BaseModel):
    items: list[ShoppingListItemOut]
    total_cost: float
    items_missing_price: int


class TrendNutrientOut(BaseModel):
    key: str
    name: str
    unit: str
    avg_amount: float
    adult_drv: float | None
    avg_percent_drv: float | None
    drv_source: str | None
    drv_confidence: str | None
    drv_methodology_version: str
    goal_adjusted: bool = False

    @classmethod
    def build(
        cls,
        key: str,
        nutrient_def: NutrientDef,
        avg_amount: float,
        drv: float | None,
        *,
        drv_source: str | None = None,
        drv_confidence: str | None = None,
        goal_adjusted: bool = False,
    ) -> "TrendNutrientOut":
        """See NutrientAmountOut.build — same shaping logic, different
        field names (avg_amount/avg_percent_drv) for the trends endpoint."""
        return cls(
            key=key,
            name=nutrient_def.name,
            unit=nutrient_def.unit,
            avg_amount=avg_amount,
            adult_drv=drv,
            avg_percent_drv=(avg_amount / drv * 100) if drv else None,
            drv_source=drv_source if drv_source is not None else (nutrient_def.drv_source or None),
            drv_confidence=(
                drv_confidence
                if drv_confidence is not None
                else (nutrient_def.drv_confidence if nutrient_def.drv_source else None)
            ),
            drv_methodology_version=DRV_METHODOLOGY_VERSION,
            goal_adjusted=goal_adjusted,
        )


class TrendBucketOut(BaseModel):
    bucket_start: date
    bucket_end: date
    logged_days: int
    nutrients: list[TrendNutrientOut]


class DiaryTrendsOut(BaseModel):
    group_by: Literal["week", "month"]
    buckets: list[TrendBucketOut]


class WeightLogCreate(BaseModel):
    log_date: date
    weight_kg: float = Field(gt=0)


class WeightLogOut(BaseModel):
    id: int
    log_date: date
    weight_kg: float


FilterOp = Literal["gte", "lte", "eq"]


class NutrientFilterIn(BaseModel):
    key: str
    op: FilterOp
    value: float


class SearchRequest(BaseModel):
    filters: list[NutrientFilterIn]
    limit: int = 100


class FilterKeyOut(BaseModel):
    key: str
    label: str
    unit: str | None


Scope = Literal["food", "recipe"]


class SavedFilterPresetCreate(BaseModel):
    name: str
    scope: Scope
    filters: list[NutrientFilterIn]


class SavedFilterPresetOut(BaseModel):
    id: int
    name: str
    scope: Scope
    filters: list[NutrientFilterIn]


class ApiKeyCreate(BaseModel):
    name: str


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    created_at: datetime
    revoked_at: datetime | None
    quota_limit: int
    requests_this_period: int
    period_started_at: date


class ApiKeyCreatedOut(ApiKeyOut):
    # only present on the create response — the one and only time the raw
    # key is ever visible; not retrievable again afterward
    key: str


class IronBioavailabilityRequestItem(BaseModel):
    food_id: int
    quantity_g: float


class IronBioavailabilityRequest(BaseModel):
    items: list[IronBioavailabilityRequestItem]


class IronBioavailabilityResultOut(BaseModel):
    heme_iron_mg: float
    non_heme_iron_mg: float
    vitamin_c_mg: float
    absorbed_heme_mg: float
    absorbed_non_heme_mg: float
    absorbed_total_mg: float
    non_heme_absorption_tier: str
    iron_split_source: str


class ClinicianInviteCreate(BaseModel):
    client_email: str


ClinicianLinkStatus = Literal["pending", "active", "revoked"]


class ClinicianLinkOut(BaseModel):
    id: int
    clinician_email: str
    client_email: str
    client_user_id: int
    status: ClinicianLinkStatus
    created_at: datetime
    responded_at: datetime | None


class ClinicianNoteCreate(BaseModel):
    note_text: str


class ClinicianNoteOut(BaseModel):
    id: int
    note_text: str
    created_at: datetime


class ClinicianClientSummaryOut(BaseModel):
    client_email: str
    day: DiarySummaryOut


class IngredientSuggestionOut(BaseModel):
    """One `recommend_ingredients.IngredientSuggestion` — prompt 6.
    `score` is the total from `recommendation_scoring.ScoreBreakdown`;
    the full breakdown isn't exposed here to keep the default response
    compact (prompt 10's "do not overwhelm users with every nutrient by
    default") — see the /ingredients/{food_id}/explain-style detail if a
    future prompt needs the full breakdown surfaced."""

    food_id: int
    food_name: str
    quantity_g: float
    candidate_kind: str
    score: float
    nutrients_improved: list[str]
    remaining_shortfalls: list[str]
    new_warnings: list[str]
    extra_energy_kcal: float
    data_coverage: float
    explanation: str


class IngredientSuggestionsOut(BaseModel):
    suggestions: list[IngredientSuggestionOut]


class RecipeSuggestionOut(BaseModel):
    """One `recommend_recipes.RecipeSuggestion` — prompt 7."""

    recipe_id: int
    recipe_name: str
    suggested_servings: float
    energy_added_kcal: float
    protein_added_g: float
    score: float
    nutrients_improved: list[str]
    remaining_shortfalls: list[str]
    new_warnings: list[str]
    is_stock: bool
    source_name: str | None
    match_coverage_lines: float | None
    robustness_rating: int | None
    robustness_note: str | None
    explanation: str


class RecipeSuggestionsOut(BaseModel):
    suggestions: list[RecipeSuggestionOut]
