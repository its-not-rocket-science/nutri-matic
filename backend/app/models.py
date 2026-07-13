from datetime import date, datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # profile fields (Phase 3) — always 1:1 with the user, no reason for a
    # separate table. Nullable because a fresh registration has none of
    # these set yet.
    sex: Mapped[str | None] = mapped_column(String, nullable=True)  # "male" | "female"
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pregnant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lactating: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # needed for energy.py's BMR calculation — nullable since not required
    # to use the rest of the app, only for a personalized calorie target
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)


class Food(Base):
    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    protein_g_per_100g: Mapped[float] = mapped_column(Float, nullable=False)

    # mg indispensable amino acid per g protein; keys match reference_patterns.AMINO_ACIDS.
    # Individual values may be null where source data doesn't cover that amino acid.
    amino_acids: Mapped[dict] = mapped_column(JSON, nullable=False)

    # per-amino-acid true ileal digestibility coefficients (0-1), for DIAAS
    digestibility_diaas: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # provenance of digestibility_diaas: "measured" (published coefficient for this
    # specific food) or "estimated" (broad food-category fallback), null if unset
    digestibility_diaas_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # single overall crude protein digestibility coefficient (0-1), for PDCAAS
    digestibility_pdcaas: Mapped[float | None] = mapped_column(Float, nullable=True)

    # provenance of digestibility_pdcaas: "measured" (published coefficient for this
    # specific food) or "estimated" (broad food-category fallback), null if unset
    digestibility_pdcaas_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # USDA FoodData Central provenance, null for manually-entered foods
    fdc_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True, index=True)
    data_type: Mapped[str | None] = mapped_column(String, nullable=True)


class FoodNutrient(Base):
    __tablename__ = "food_nutrients"
    __table_args__ = (UniqueConstraint("food_id", "nutrient_key", name="uq_food_nutrient"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(Integer, ForeignKey("foods.id"), nullable=False, index=True)
    # key into nutrients.NUTRIENTS
    nutrient_key: Mapped[str] = mapped_column(String, nullable=False)
    # amount per 100g of food, in the unit nutrients.NUTRIENTS[nutrient_key].unit
    amount_per_100g: Mapped[float] = mapped_column(Float, nullable=False)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    servings: Mapped[float] = mapped_column(Float, nullable=False)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    food_id: Mapped[int] = mapped_column(Integer, ForeignKey("foods.id"), nullable=False)
    quantity_g: Mapped[float] = mapped_column(Float, nullable=False)


class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    __table_args__ = (
        # exactly one of (food_id, quantity_g) / (recipe_id, quantity_servings)
        CheckConstraint(
            "(food_id IS NOT NULL AND quantity_g IS NOT NULL AND recipe_id IS NULL AND quantity_servings IS NULL) "
            "OR (recipe_id IS NOT NULL AND quantity_servings IS NOT NULL AND food_id IS NULL AND quantity_g IS NULL)",
            name="ck_diary_entry_exactly_one_of_food_or_recipe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal: Mapped[str] = mapped_column(String, nullable=False)  # "breakfast" | "lunch" | "dinner" | "snack"

    food_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("foods.id"), nullable=True)
    quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    # a recipe entry is logged in servings (recipes are already computed
    # per-serving) rather than grams, since a recipe's total mass isn't tracked
    recipe_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=True)
    quantity_servings: Mapped[float | None] = mapped_column(Float, nullable=True)


class SavedFilterPreset(Base):
    __tablename__ = "saved_filter_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # "food" | "recipe"
    # list of {"key": str, "op": "gte"|"lte"|"eq", "value": float} — same
    # shape as search.NutrientFilter, validated against FOOD_FILTER_KEYS /
    # RECIPE_FILTER_KEYS at save time in routers/presets.py
    filters: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
