"""Goal-adjusted daily calorie target — applies a weight-loss deficit to
the personalized EER (energy.py) when the user's profile goal calls for
one, so %DRV-against-calories reflects what they're actually trying to
do rather than plain maintenance.

Deficit size: 15% below EER for adults, reduced to 10% for adults 65+
(same OLDER_ADULT_AGE_THRESHOLD as protein_requirement.py/food_chemistry.py)
— older adults restricting calories are at greater risk of losing lean
mass alongside fat, a concern well documented in geriatric nutrition
literature (e.g. Villareal et al. 2011, NEJM, on combined diet+exercise
weight-loss interventions in older adults recommending a more conservative
approach than younger adults), so a smaller deficit is used.

15% itself isn't a single official number from one body — it sits inside
the commonly-reproduced "moderate, sustainable" ~10-20% range used across
mainstream sports-nutrition/dietetics guidance for general (non-athlete,
non-clinical) fat loss: more conservative than 20-25%+ (typically only
recommended under supervision), and often smaller than the popular
"500kcal/day" rule of thumb (which is itself a *larger* percentage for
anyone below-average maintenance calories, since it's a flat number, not
a %). Treat 15%/10% as a reasonable, safety-conscious default, not a
clinical prescription — this app has no way to know if a larger or
smaller deficit is right for a specific person, and doesn't pretend to.

Floor: the target never goes below 1,200kcal/day (women) or 1,500kcal/day
(men) — minimums commonly reproduced in NIH/NHLBI-style guidance and
widely echoed by registered-dietitian sources as the point below which
unsupervised dieting risks micronutrient inadequacy. Whichever number (the
% deficit or the floor) is *higher* wins, so the floor only ever raises
the target, never lowers it further.

Pregnancy/lactation: never deficit-adjusted, regardless of goal — active
calorie restriction during pregnancy or lactation is generally not
considered safe without direct clinical supervision, so this always
falls back to plain EER (which already includes those states' flat
increments) for those profiles.

"visceral_fat_reduction" gets the exact same calculation as "weight_loss".
Visceral fat responds to the same overall energy-deficit mechanism as
subcutaneous fat — there's no separate, established way to calorie-target
one fat depot over another, and inventing a different number for it would
be exactly the fabricated precision this app avoids elsewhere.
"""

from .energy import calculate_age, calculate_eer
from .food_chemistry import OLDER_ADULT_AGE_THRESHOLD
from .models import User

WEIGHT_LOSS_GOALS = {"weight_loss", "visceral_fat_reduction"}

DEFICIT_PERCENT_ADULT = 0.15
DEFICIT_PERCENT_OLDER_ADULT = 0.10

CALORIE_FLOOR_FEMALE_KCAL = 1200.0
CALORIE_FLOOR_MALE_KCAL = 1500.0


def calculate_energy_target(user: User, *, current_year: int | None = None) -> tuple[float, bool] | None:
    """Returns (target_kcal, deficit_applied), or None if EER itself can't
    be computed (see energy.calculate_eer for required fields).

    deficit_applied is True only when a weight-loss goal is set, the user
    isn't pregnant/lactating, and the deficit actually landed below EER
    (i.e. the floor didn't erase it entirely) — so callers can show an
    honest "this reflects your weight-loss goal" note only when the target
    is actually different from plain maintenance, never unconditionally."""
    eer = calculate_eer(user, current_year=current_year)
    if eer is None:
        return None
    if user.goal not in WEIGHT_LOSS_GOALS or user.is_pregnant or user.is_lactating:
        return (eer, False)

    age = calculate_age(user, current_year=current_year)
    deficit_percent = (
        DEFICIT_PERCENT_OLDER_ADULT
        if age is not None and age >= OLDER_ADULT_AGE_THRESHOLD
        else DEFICIT_PERCENT_ADULT
    )
    floor = CALORIE_FLOOR_MALE_KCAL if user.sex == "male" else CALORIE_FLOOR_FEMALE_KCAL

    target = max(eer * (1 - deficit_percent), floor)
    return (target, target < eer)
