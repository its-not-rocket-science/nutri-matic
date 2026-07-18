"""Personalized daily protein target — grams/day, from body weight and
activity level, with an age-based floor for older adults. Same overall
shape as energy.py's EER calculation (a formula, not a sex/life-stage
table lookup), because protein needs likewise depend on the individual's
own weight rather than a population average.

g/kg-bodyweight-per-activity-tier figures are commonly reproduced across
sports nutrition literature (ISSN/ACSM position stands; Jäger et al.
2017, J Int Soc Sports Nutr, "International Society of Sports Nutrition
Position Stand: protein and exercise") rather than a single official
table — WHO/FAO/UNU (2007) establishes only the sedentary-adult baseline
(0.83g/kg safe intake, rounded to 0.8 here for a clean 5-tier ladder
matching this app's existing activity_level values). Not citable to one
precise source per tier; treat the non-sedentary figures as a reasonable
approximation, not a clinical prescription.

Age: healthy adults 65+ need more protein per kg than younger sedentary
adults to counter age-related anabolic resistance — the PROT-AGE Study
Group (Bauer et al. 2013, J Am Med Dir Assoc) recommends at least
1.0-1.2g/kg regardless of activity level. Applied here as a floor: an
older adult gets whichever is higher, their activity tier's figure or
this floor — never less than a younger sedentary adult on the same
activity tier would get.

Sex isn't an independent multiplier here — real per-kg dosing is already
sex-neutral once actual bodyweight is known, unlike energy's BMR formula
(which corrects for average lean-mass differences a per-kg protein
figure doesn't need, since the target already scales with the
individual's own weight). It still enters through pregnancy/lactation,
same flat-increment convention as energy.py's kcal increments — UK
COMA/SACN protein RNI increments, not trimester/month-specific.
"""

from .energy import calculate_age
from .food_chemistry import OLDER_ADULT_AGE_THRESHOLD
from .models import User

PROTEIN_G_PER_KG_BY_ACTIVITY = {
    "sedentary": 0.8,
    "light": 1.0,
    "moderate": 1.2,
    "active": 1.4,
    "very_active": 1.6,
}

# PROT-AGE Study Group (Bauer et al. 2013) — healthy older adults should get
# at least this much per kg, regardless of activity tier
OLDER_ADULT_PROTEIN_G_PER_KG_FLOOR = 1.0

PROTEIN_PREGNANCY_INCREMENT_G = 6
PROTEIN_LACTATION_INCREMENT_G = 11


def calculate_protein_target_g(user: User, *, current_year: int | None = None) -> float | None:
    """None if the profile is incomplete — weight, birth year, and
    activity level are all required inputs."""
    if None in (user.weight_kg, user.birth_year, user.activity_level):
        return None

    age = calculate_age(user, current_year=current_year)
    g_per_kg = PROTEIN_G_PER_KG_BY_ACTIVITY[user.activity_level]
    if age is not None and age >= OLDER_ADULT_AGE_THRESHOLD:
        g_per_kg = max(g_per_kg, OLDER_ADULT_PROTEIN_G_PER_KG_FLOOR)

    target = g_per_kg * user.weight_kg
    if user.is_pregnant:
        target += PROTEIN_PREGNANCY_INCREMENT_G
    if user.is_lactating:
        target += PROTEIN_LACTATION_INCREMENT_G
    return target
