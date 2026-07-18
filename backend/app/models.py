from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
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

    # Phase 3 — dietary pattern is a single overriding choice (you are
    # either vegan or you aren't), unlike allergies/religious requirements/
    # preferences below, which are inherently multiple and live in
    # DietaryConstraint. Nullable: not set means "no pattern declared",
    # not "omnivore" — the two are different (a fresh signup has never
    # said either way). See dietary_tags.py for what each pattern implies.
    dietary_pattern: Mapped[str | None] = mapped_column(String, nullable=True)

    # ISO 4217 code (e.g. "USD", "GBP"). Null means "not set" — the
    # frontend defaults to whatever the user's browser locale implies in
    # that case, only falling back to this column when they've explicitly
    # overridden it in their profile. Never guessed/defaulted server-side:
    # the browser is the only thing that actually knows the user's locale.
    currency: Mapped[str | None] = mapped_column(String, nullable=True)

    # onboarding's step-1 pick ("protein_quality" | "nutrient_gaps" | "budget"
    # | "exploring") — persisted so it can personalize the dashboard/
    # recommendations beyond onboarding's own closing message, and so it's
    # editable later rather than a one-time-only signal. Null means never
    # set (skipped onboarding, or a pre-this-feature account), not any
    # specific goal.
    goal: Mapped[str | None] = mapped_column(String, nullable=True)

    # entitlement primitive (Phase 3) — see entitlements.py. A plain string,
    # not a DB enum: adding "educational"/"enterprise" later is just a new
    # string value used in entitlements.py's tables, no migration needed.
    plan: Mapped[str] = mapped_column(String, nullable=False, default="free", server_default="free")
    # only meaningful when plan == "trial" — null for free/paid. A trial
    # whose expiry has passed is treated as "free" by entitlements.py
    # (see user_has_feature), not auto-downgraded in the database itself.
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DietaryConstraint(Base):
    """A user's allergy, intolerance, religious requirement, or preference —
    see dietary_tags.py for the controlled vocabulary and how each tag maps
    to a keyword-based food match. Medical considerations and free-text
    preferences are NOT enforced as filters (see dietary_tags.py's module
    docstring for why) and are stored with tag=None, note=<free text>
    instead — informational only, shown on the profile but never used to
    exclude a food/recipe from search or the optimizer."""

    __tablename__ = "dietary_constraints"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "tag", name="uq_dietary_constraint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # "allergy" | "intolerance" | "religious" | "medical" | "preference"
    category: Mapped[str] = mapped_column(String, nullable=False)
    # a dietary_tags.py vocabulary key (e.g. "peanut", "halal") for
    # allergy/intolerance/religious/preference rows; null for medical rows
    # and any free-text preference not in the controlled vocabulary
    tag: Mapped[str | None] = mapped_column(String, nullable=True)
    # "hard_exclude" (never show/suggest) | "avoid" (soft — flagged, not
    # hidden); null for medical/informational rows, which aren't enforced
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class Food(Base):
    __tablename__ = "foods"
    __table_args__ = (
        # search.py's search_foods_by_name/search_foods (ILIKE '%term%') and
        # its pg_trgm similarity() fallback, plus demo_data.py's seeding
        # lookups, all filter on Food.name with a leading wildcard — a
        # plain btree index can't help there. Measured on the real 1.4M-row
        # ingested catalog: demo account creation (6 name lookups) took
        # ~6.6s without this index; a GIN trigram index is what pg_trgm's
        # own docs recommend for exactly this substring/similarity pattern.
        # No-ops (falls back to a plain index) on SQLite, which the test
        # suite uses — trigram matching there is untested by design, since
        # search.py already gates the fuzzy path on postgresql specifically.
        Index("ix_foods_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
    )

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
    __table_args__ = (
        UniqueConstraint("food_id", "nutrient_key", name="uq_food_nutrient"),
        # Phase 5.2 technical audit: _rank_foods_by_nutrient() (gap-suggestions,
        # meal-optimize — both diary and meal-plan versions) filters by
        # nutrient_key and sorts by amount_per_100g descending on every call.
        # At 222k real ingested rows this was a 137ms parallel sequential
        # scan with no supporting index — this composite index serves that
        # exact filter+sort directly. See docs/production-readiness-audit.md.
        Index("ix_food_nutrients_key_amount", "nutrient_key", "amount_per_100g"),
    )

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
    # visible to every user regardless of ownership/RecipeShare — for
    # curated stock recipes. Still owner-only to edit/delete/add-to-collection;
    # this only widens read access. Not settable via the API (no
    # RecipeCreate/RecipeUpdate field for it), only ever set directly in the db.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # both optional — a recipe built directly in-app has neither. source_url
    # is where the recipe came from (if anywhere); method is free-text
    # cooking instructions, shown collapsed by default on the recipe page
    # since ingredients/scoring are this app's focus, not step-by-step prep.
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String, nullable=True)


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
    # same meaning as Recipe.is_public — visible to every user, but only
    # the owner can rename/delete it or add/remove recipes. Not settable
    # via the API, only ever set directly in the db.
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


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


class DiarySnapshot(Base):
    """A frozen copy of a diary day's computed nutrient breakdown, taken
    explicitly by the user (not automatic — see docs/live-vs-snapshot-mode.md
    for why). Immutable once created: the whole point is that Snapshot Mode
    reproduces exactly what was computed at snapshot time, even after
    methodology_version moves on. Days never snapshotted only ever exist in
    Live Mode — this table does not retroactively cover diary history from
    before this feature existed."""

    __tablename__ = "diary_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "entry_date", name="uq_diary_snapshot_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # the DiarySummaryOut-shaped payload, as JSON, exactly as computed at
    # snapshot time — see routers/diary.py's snapshot endpoint
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    drv_methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    scoring_methodology_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class ApiKey(Base):
    """A public-API credential (Phase 3.2) — separate from the JWT session
    auth used everywhere else in the app. Keys are created via the JWT-
    authed /api/api-keys endpoints and then used, via the X-API-Key header,
    against the versioned /api/v1/* public endpoints. See api_keys.py."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # sha256 of the actual key — see api_keys.py::hash_api_key for why
    # sha256 rather than bcrypt for this. The raw key is shown to the user
    # exactly once, at creation; only its hash is ever stored.
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # first few characters of the raw key, stored in the clear so a user
    # can tell their keys apart in a list without the full secret being
    # displayable again
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quota_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1000, server_default="1000")
    requests_this_period: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    period_started_at: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)


class ClinicianClientLink(Base):
    """Grants a clinician (any registered user acting as one — this app has
    no license-verification mechanism, see docs/professional-dashboard-scope.md)
    read access to a client's diary data, subject to the client's explicit
    consent. Deliberately NOT a direct grant-by-email like RecipeShare —
    unlike sharing a recipe you own, this grants access to someone else's
    private health data, so it requires the client to accept before
    `status` moves from "pending" to "active". Either party can revoke."""

    __tablename__ = "clinician_client_links"
    __table_args__ = (UniqueConstraint("clinician_user_id", "client_user_id", name="uq_clinician_client"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinician_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    client_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # "pending" | "active" | "revoked"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClinicianNote(Base):
    """A clinician's private note about a client — never exposed to the
    client themselves via any endpoint. Requires an active
    ClinicianClientLink to create or read (enforced in routers/clinician.py,
    not at the DB layer)."""

    __tablename__ = "clinician_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clinician_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    client_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    note_text: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )


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
