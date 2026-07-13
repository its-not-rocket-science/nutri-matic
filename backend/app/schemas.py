from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Sex = Literal["male", "female"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]


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


class ProfileUpdate(BaseModel):
    sex: Sex | None = None
    birth_year: int | None = None
    activity_level: ActivityLevel | None = None
    is_pregnant: bool = False
    is_lactating: bool = False


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
