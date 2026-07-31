"""Goal-aware nutrient-priority weighting (prompt 2.2).

Prompt 2.1 decided the policy for combining multiple active goals
(priority-weighted sum — see goals.goal_weight) but nothing actually
consumed it: as of that prompt, `goal` only gated the weight-loss calorie
deficit and picked a cosmetic dashboard message, neither of which is
recommendation scoring. This module is the first real consumer — it lets
a profile's active goals influence *which* nutrient gap /gap-suggestions
and /meal-optimize target (`_find_worst_gap`, routers/diary.py, shared by
both), not just gate an unrelated calculation.

Each goal below names the nutrient keys it emphasizes and a flat
per-nutrient boost factor for that goal — chosen deliberately modest
(1.3, a 30% boost) so a genuinely severe gap in an unrelated nutrient
still wins; goals nudge which of several comparably-sized gaps gets
targeted, they don't override real physiological need. Boosts from every
active goal that emphasizes a given nutrient combine via
goals.goal_weight(rank) into one effective multiplier per nutrient;
`_find_worst_gap` divides each candidate's percent_drv by its multiplier
before picking the minimum, so a goal-emphasized nutrient effectively
looks more urgent — mechanically the same "lower %DRV wins" comparison,
just goal-aware.

Kept to nutrients this app already tracks (`NUTRIENTS` in nutrients.py)
rather than anything requiring new data — and, more specifically, kept to
nutrients `_find_worst_gap` can actually select at all. That function
only ever compares candidates with a real `percent_drv` (i.e.
`optimisation_eligible=True` in nutrients.py — a nutrient with an actual
upward DRV target), so a nutrient here that isn't optimisation-eligible
would be an advertised boost that can never fire (PR review: this caught
`epa`/`dha`, which nutrients.py deliberately has no individual DRV for —
EFSA/WHO only publish a combined EPA+DHA target — and `sodium`, which is
a maximum-guideline nutrient with no upward target at all, never a
"gap"). `energy` is excluded from this module for the identical reason —
`_find_worst_gap` never treats a calorie target as "a gap" either.

Evidence basis per goal, framed as "aligned with research on X" per this
prompt's own instruction — never a promise of an outcome this app has no
way to verify for any individual:

- longevity: protein (adequacy/timing — higher intakes increasingly
  recommended for healthy aging/sarcopenia prevention, e.g. the
  "double protein intake" older-adult research), fiber_total (a
  consistent, large-cohort association with lower all-cause/
  cardiometabolic mortality), ala (omega-3 intake and cardiovascular
  mortality reduction — the one omega-3 fatty acid nutrients.py gives an
  individual DRV to; EPA/DHA only have a combined, non-optimisable
  target, see above), magnesium and potassium (both repeatedly
  associated with cardiometabolic/longevity outcomes in epidemiological
  literature).
- athletic_stamina (endurance): iron (endurance training's well-
  documented depletion risk — foot-strike haemolysis, expanded plasma
  volume) and potassium (sweat electrolyte replacement — sodium itself
  is excluded, see above, since it has no upward target to ever rank
  against).
- athletic_strength: protein (muscle protein synthesis), calcium and
  magnesium (bone loading and muscle-contraction function), zinc
  (commonly depleted by heavy training; immune/hormonal role).
- athletic_power: protein, phosphorus (the ATP/phosphocreatine
  fast-energy system power output actually draws on — the nutritional
  distinction from strength training's slower, more sustained
  contractions), zinc.

Deliberately NOT implemented, despite being reasonable candidates —
flagged rather than forced in with weak support, per this prompt's own
instruction:

- blood-sugar stability: would need glycaemic-index/load data this
  app's FDC-derived catalogue doesn't carry for the large majority of
  foods (GI is a lab-measured value FDC doesn't publish).
- a broader "recovery/anti-inflammatory" goal beyond the omega-3 signal
  already covered under longevity: would need polyphenol/antioxidant
  data FDC doesn't track at all.

reduce_carbon_footprint is intentionally absent from this module — it's
a property of candidate *foods* (see carbon_footprint.py's coarse,
explicitly low-confidence category tiering), not a nutrient target, so
it doesn't fit `_find_worst_gap`'s nutrient-gap model at all.
"""

from .goals import goal_weight

GOAL_NUTRIENT_EMPHASIS: dict[str, dict[str, float]] = {
    "longevity": {
        "protein": 1.3, "fiber_total": 1.3, "ala": 1.3, "magnesium": 1.3, "potassium": 1.3,
    },
    "athletic_stamina": {"iron": 1.3, "potassium": 1.3},
    "athletic_strength": {"protein": 1.3, "calcium": 1.3, "magnesium": 1.3, "zinc": 1.3},
    "athletic_power": {"protein": 1.3, "phosphorus": 1.3, "zinc": 1.3},
}


def nutrient_priority_multipliers(goal_keys: list[str]) -> dict[str, float]:
    """`goal_keys`: a profile's active goals, highest priority first
    (index 0 = priority 1) — see goals.load_goal_keys/goal_keys_of.
    Returns {nutrient_key: multiplier}, present only for nutrients at
    least one active goal emphasizes; every other nutrient implicitly
    stays at the neutral 1.0 for the caller."""
    multipliers: dict[str, float] = {}
    for rank, goal in enumerate(goal_keys, start=1):
        emphasis = GOAL_NUTRIENT_EMPHASIS.get(goal)
        if emphasis is None:
            continue
        weight = goal_weight(rank)
        for nutrient_key, boost in emphasis.items():
            # (boost - 1) is the "extra" beyond neutral; weight it by this
            # goal's priority rank, then add to whatever's already there
            # so multiple active goals that both emphasize this nutrient
            # stack (each contributes independently, per goals.py's
            # documented weighting policy)
            multipliers[nutrient_key] = multipliers.get(nutrient_key, 1.0) + weight * (boost - 1.0)
    return multipliers
