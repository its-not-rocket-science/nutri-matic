"""Phase 3 demo mode: a one-click, fully private sandbox account seeded
with realistic data, so a prospective user can explore the dashboard,
diary, recipes, meal plan, and weight log before ever entering their own
data.

Deliberately a REAL account per visitor rather than one shared "demo"
login — a shared account that anyone can edit would get vandalised or
just confusing (whose diary entries are these?) within a day. Each demo
account gets a random, never-communicated password (the caller only ever
receives a bearer token, exactly like register/login) and a throwaway
email under a reserved local domain, so these are trivially identifiable
and safe to purge later without touching real users.
"""

import secrets
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .auth import create_access_token, hash_password
from .models import DiaryEntry, Food, FoodPrice, MealPlanEntry, Recipe, RecipeIngredient, User, WeightLog

DEMO_EMAIL_DOMAIN = "demo.nutrimatic.local"

# Ordered by preference; the first real match (by data_type priority, then
# name) for each search term is used. Foundation/SR Legacy preferred over
# branded for the same reason search ranking does — a cleaner, more
# recognizable name for a demo.
DEMO_FOOD_SEARCH_TERMS = [
    "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
    "Egg, whole, cooked, hard-boiled",
    "Rice, white, long-grain, regular, cooked",
    "Broccoli, raw",
    "Lentils, mature seeds, cooked, boiled, without salt",
    "Yogurt, Greek, plain, whole milk",
]


def _find_demo_foods(db: Session) -> dict[str, Food]:
    found: dict[str, Food] = {}
    for term in DEMO_FOOD_SEARCH_TERMS:
        food = (
            db.query(Food)
            .filter(Food.name.ilike(f"%{term}%"))
            .order_by(Food.data_type.isnot(None).desc(), Food.name)
            .first()
        )
        if food is not None:
            found[term] = food
    return found


def create_demo_account(db: Session) -> str:
    """Creates the account, seeds it, and returns a ready-to-use bearer
    token — the caller never sees or needs the generated credentials."""
    email = f"demo-{secrets.token_hex(6)}@{DEMO_EMAIL_DOMAIN}"
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(24)),
        sex="female",
        birth_year=date.today().year - 32,
        activity_level="moderate",
        weight_kg=65.0,
        height_cm=168.0,
    )
    db.add(user)
    db.flush()

    foods = _find_demo_foods(db)
    today = date.today()

    def food(term: str) -> Food | None:
        return foods.get(term)

    chicken = food(DEMO_FOOD_SEARCH_TERMS[0])
    egg = food(DEMO_FOOD_SEARCH_TERMS[1])
    rice = food(DEMO_FOOD_SEARCH_TERMS[2])
    broccoli = food(DEMO_FOOD_SEARCH_TERMS[3])
    lentils = food(DEMO_FOOD_SEARCH_TERMS[4])
    yogurt = food(DEMO_FOOD_SEARCH_TERMS[5])

    # Two days of a plausible, varied diary
    if egg:
        db.add(DiaryEntry(user_id=user.id, entry_date=today, meal="breakfast", food_id=egg.id, quantity_g=100))
    if yogurt:
        db.add(DiaryEntry(user_id=user.id, entry_date=today, meal="breakfast", food_id=yogurt.id, quantity_g=150))
    if chicken and rice:
        db.add(DiaryEntry(user_id=user.id, entry_date=today, meal="lunch", food_id=chicken.id, quantity_g=150))
        db.add(DiaryEntry(user_id=user.id, entry_date=today, meal="lunch", food_id=rice.id, quantity_g=180))
    if broccoli:
        db.add(DiaryEntry(user_id=user.id, entry_date=today, meal="dinner", food_id=broccoli.id, quantity_g=120))
    if lentils:
        yesterday = today - timedelta(days=1)
        db.add(DiaryEntry(user_id=user.id, entry_date=yesterday, meal="dinner", food_id=lentils.id, quantity_g=200))

    # A simple recipe, so /recipes isn't empty either
    if chicken and rice:
        recipe = Recipe(user_id=user.id, name="Chicken & rice bowl", servings=2)
        db.add(recipe)
        db.flush()
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=chicken.id, quantity_g=300))
        db.add(RecipeIngredient(recipe_id=recipe.id, food_id=rice.id, quantity_g=300))

    # Tomorrow's meal plan, plus a price so the shopping-list budget shows
    # something other than "missing a price"
    if lentils:
        db.add(
            MealPlanEntry(
                user_id=user.id, plan_date=today + timedelta(days=1), meal="dinner",
                food_id=lentils.id, quantity_g=200,
            )
        )
        db.add(FoodPrice(user_id=user.id, food_id=lentils.id, package_price=3.20, package_quantity_g=500))

    db.add(WeightLog(user_id=user.id, log_date=today - timedelta(days=7), weight_kg=65.8))
    db.add(WeightLog(user_id=user.id, log_date=today, weight_kg=65.0))

    db.commit()
    return create_access_token(user.id)
