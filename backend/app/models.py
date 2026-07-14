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

    # UPC/EAN barcode, from FDC's Branded Foods dataset — null for
    # Foundation/SR Legacy foods, which aren't sold as packaged retail items
    gtin_upc: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)


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


class RecipeShare(Base):
    __tablename__ = "recipe_shares"
    __table_args__ = (UniqueConstraint("recipe_id", "shared_with_user_id", name="uq_recipe_share"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    shared_with_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class RecipeRating(Base):
    __tablename__ = "recipe_ratings"
    __table_args__ = (UniqueConstraint("recipe_id", "user_id", name="uq_recipe_rating"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5, enforced in schemas.RecipeRatingCreate
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class RecipeComment(Base):
    __tablename__ = "recipe_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    body: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class RecipeTag(Base):
    __tablename__ = "recipe_tags"
    __table_args__ = (UniqueConstraint("recipe_id", "tag", name="uq_recipe_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)
    # denormalized string rather than a separate Tag entity — tags are
    # scoped to whoever owns the recipe (no cross-user tag reuse/renaming
    # to worry about), so there's nothing a normalized Tag table would buy
    tag: Mapped[str] = mapped_column(String, nullable=False, index=True)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class CollectionRecipe(Base):
    __tablename__ = "collection_recipes"
    __table_args__ = (UniqueConstraint("collection_id", "recipe_id", name="uq_collection_recipe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey("collections.id"), nullable=False, index=True)
    # the recipe doesn't have to be owned by the collection's owner — a
    # recipe shared with you can be filed into your own collection too,
    # same as it can be copied; unlike copying, this doesn't clone anything
    recipe_id: Mapped[int] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=False, index=True)


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


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        # exactly one of (food_id, quantity_g) / (recipe_id, quantity_servings) — same shape as DiaryEntry
        CheckConstraint(
            "(food_id IS NOT NULL AND quantity_g IS NOT NULL AND recipe_id IS NULL AND quantity_servings IS NULL) "
            "OR (recipe_id IS NOT NULL AND quantity_servings IS NOT NULL AND food_id IS NULL AND quantity_g IS NULL)",
            name="ck_meal_plan_entry_exactly_one_of_food_or_recipe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    meal: Mapped[str] = mapped_column(String, nullable=False)  # "breakfast" | "lunch" | "dinner" | "snack"

    food_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("foods.id"), nullable=True)
    quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    recipe_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=True)
    quantity_servings: Mapped[float | None] = mapped_column(Float, nullable=True)


class FoodPrice(Base):
    __tablename__ = "food_prices"
    __table_args__ = (UniqueConstraint("user_id", "food_id", name="uq_food_price_user_food"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    food_id: Mapped[int] = mapped_column(Integer, ForeignKey("foods.id"), nullable=False, index=True)
    # what the user actually sees on the shelf/receipt — price-per-100g is
    # derived from these at query time rather than stored, so re-editing
    # either field doesn't require the user to redo any unit conversion
    package_price: Mapped[float] = mapped_column(Float, nullable=False)
    package_quantity_g: Mapped[float] = mapped_column(Float, nullable=False)


class MealPlanTemplate(Base):
    __tablename__ = "meal_plan_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class MealPlanTemplateEntry(Base):
    __tablename__ = "meal_plan_template_entries"
    __table_args__ = (
        # exactly one of (food_id, quantity_g) / (recipe_id, quantity_servings) — same shape as MealPlanEntry
        CheckConstraint(
            "(food_id IS NOT NULL AND quantity_g IS NOT NULL AND recipe_id IS NULL AND quantity_servings IS NULL) "
            "OR (recipe_id IS NOT NULL AND quantity_servings IS NOT NULL AND food_id IS NULL AND quantity_g IS NULL)",
            name="ck_meal_plan_template_entry_exactly_one_of_food_or_recipe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("meal_plan_templates.id"), nullable=False, index=True)
    # 0 = Monday .. 6 = Sunday, relative to whatever week the template gets applied to —
    # a template has no absolute dates of its own, that's the whole point of it being reusable
    day_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    meal: Mapped[str] = mapped_column(String, nullable=False)  # "breakfast" | "lunch" | "dinner" | "snack"

    food_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("foods.id"), nullable=True)
    quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    recipe_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=True)
    quantity_servings: Mapped[float | None] = mapped_column(Float, nullable=True)


class DiaryMealTemplate(Base):
    __tablename__ = "diary_meal_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class DiaryMealTemplateItem(Base):
    __tablename__ = "diary_meal_template_items"
    __table_args__ = (
        # exactly one of (food_id, quantity_g) / (recipe_id, quantity_servings) — same shape as DiaryEntry.
        # No date/meal here — unlike MealPlanTemplateEntry's day_offset, a meal template isn't tied to
        # any particular slot in the week, it's applied to whatever date+meal the user picks when logging.
        CheckConstraint(
            "(food_id IS NOT NULL AND quantity_g IS NOT NULL AND recipe_id IS NULL AND quantity_servings IS NULL) "
            "OR (recipe_id IS NOT NULL AND quantity_servings IS NOT NULL AND food_id IS NULL AND quantity_g IS NULL)",
            name="ck_diary_meal_template_item_exactly_one_of_food_or_recipe",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("diary_meal_templates.id"), nullable=False, index=True
    )

    food_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("foods.id"), nullable=True)
    quantity_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    recipe_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("recipes.id"), nullable=True)
    quantity_servings: Mapped[float | None] = mapped_column(Float, nullable=True)


class WeightLog(Base):
    __tablename__ = "weight_logs"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="uq_weight_log_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    log_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)


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
