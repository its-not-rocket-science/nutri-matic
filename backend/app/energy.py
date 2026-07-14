"""Personalized daily energy (calorie) target.

Unlike the vitamin/mineral DRV matrix in nutrients.py, energy needs can't
be looked up from a fixed sex/life-stage table — they depend on an
individual's weight, height, and age. This uses Mifflin-St Jeor (the
modern standard BMR equation, more accurate than the older Harris-Benedict
formula it replaced) times a standard activity multiplier.

Mifflin-St Jeor:
    men:   BMR = 10*weight_kg + 6.25*height_cm - 5*age + 5
    women: BMR = 10*weight_kg + 6.25*height_cm - 5*age - 161

Pregnancy/lactation add a flat energy increment on top (not a BMR-formula
change) — commonly cited UK SACN figures: +200 kcal/day in the last
trimester of pregnancy (applied flat here rather than trimester-aware, for
simplicity), +500 kcal/day while lactating (first 6 months).
"""

from datetime import datetime

from .models import User

# Standard PAL (physical activity level) multipliers commonly paired with
# Mifflin-St Jeor.
ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

PREGNANCY_INCREMENT_KCAL = 200
LACTATION_INCREMENT_KCAL = 500


def calculate_age(user: User, *, current_year: int | None = None) -> int | None:
    """None if birth_year isn't set — shared by the EER calculation here
    and food_chemistry.py's age-dependent leucine threshold."""
    if user.birth_year is None:
        return None
    year = current_year if current_year is not None else datetime.now().year
    return year - user.birth_year


def calculate_eer(user: User, *, current_year: int | None = None) -> float | None:
    """Estimated Energy Requirement in kcal/day, or None if the profile is
    incomplete — weight, height, birth year, sex, and activity level are
    all required inputs to the formula."""
    if None in (user.weight_kg, user.height_cm, user.birth_year, user.sex, user.activity_level):
        return None

    age = calculate_age(user, current_year=current_year)

    bmr = 10 * user.weight_kg + 6.25 * user.height_cm - 5 * age
    bmr += 5 if user.sex == "male" else -161

    eer = bmr * ACTIVITY_MULTIPLIERS[user.activity_level]

    if user.is_pregnant:
        eer += PREGNANCY_INCREMENT_KCAL
    if user.is_lactating:
        eer += LACTATION_INCREMENT_KCAL

    return eer
