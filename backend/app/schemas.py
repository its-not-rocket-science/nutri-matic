from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class FoodOut(FoodCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


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


class NutrientProvenanceOut(BaseModel):
    key: str
    name: str
    fdc_nutrient_nbr: str
    amount_per_100g: float
    drv_source: str | None
    drv_confidence: str | None


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
    ) -> "NutrientAmountOut":
        """Shared shaping logic for the four call sites that turn a
        (nutrient_def, amount, drv) triple into this schema — food/recipe
        nutrients endpoints and the diary day/trends endpoints. Callers with
        a personalized override (currently just diary's "energy" nutrient,
        whose source/confidence describe a BMR calculation rather than a
        table lookup) pass drv_source/drv_confidence explicitly; everyone
        else gets them straight from nutrient_def."""
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
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False
    weight_kg: float | None = None
    height_cm: float | None = None


class ProfileUpdate(BaseModel):
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False
    weight_kg: float | None = None
    height_cm: float | None = None


class RecipeIngredientCreate(BaseModel):
    food_id: int
    quantity_g: float


class RecipeCreate(BaseModel):
    name: str
    servings: float
    ingredients: list[RecipeIngredientCreate]


class RecipeIngredientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    food_id: int
    food_name: str
    quantity_g: float


class RecipeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    servings: float
    ingredients: list[RecipeIngredientOut]
    owner_email: str
    is_owner: bool
    average_rating: float | None
    rating_count: int
    tags: list[str]


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


class CollectionDetailOut(BaseModel):
    id: int
    name: str
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
    action: Literal["add", "swap"]
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


class MealOptimizationOut(BaseModel):
    meal: Meal
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
