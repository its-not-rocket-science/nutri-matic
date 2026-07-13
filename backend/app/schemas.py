from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class NutrientAmountOut(BaseModel):
    key: str
    name: str
    unit: str
    # per 100g for a food, per serving for a recipe, per day for a diary summary
    amount: float
    adult_drv: float | None
    percent_drv: float | None


class UserCreate(BaseModel):
    email: str
    password: str


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


class DiarySummaryOut(BaseModel):
    entries: list[DiaryEntryOut]
    nutrients: list[NutrientAmountOut]


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


class ShoppingListItemOut(BaseModel):
    food_id: int
    food_name: str
    quantity_g: float


class ShoppingListOut(BaseModel):
    items: list[ShoppingListItemOut]


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
