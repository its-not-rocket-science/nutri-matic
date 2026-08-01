"""Multi-goal profile support (prompt 2.1).

`Profile.goal` used to be the single source of truth for a profile's one
goal; it's kept as-is (an additive migration, not a destructive rework —
see migrations/versions/*_add_profile_goals.py) but is no longer read as
the source of truth anywhere except as a defensive fallback for a Profile
object that was never attached to a request-scoped goal set (e.g. one
built directly in a test fixture, without also inserting `ProfileGoal`
rows). `ProfileGoal` is the real, ordered, multi-value store going
forward.

Weighting policy, decided and documented here rather than left undefined
(prompt 2.1's own instruction, and needed by prompt 2.2's goal-aware
recommendation scoring): each active goal is an independent scoring
signal, combined as a priority-weighted sum — rank 1 gets full weight,
rank 2 half, rank 3 a third, and so on (`goal_weight(rank) == 1/rank`).
A user's first-picked goal should matter more than their fourth, but a
lower-ranked goal still nudges scoring rather than being ignored outright
or, at the other extreme, having one goal dominate completely regardless
of how many others are also active.
"""

from sqlalchemy.orm import Session

from .models import Profile, ProfileGoal

# must match the frontend's shared Goal type (lib/goals.ts). weight_loss/
# visceral_fat_reduction additionally drive a real calculation — see
# energy_goal.py's WEIGHT_LOSS_GOALS. longevity/athletic_stamina/
# athletic_strength/athletic_power drive nutrient-priority weighting in
# gap-suggestions/meal-optimize — see goal_nutrient_priorities.py.
# reduce_carbon_footprint nudges candidate ranking in recommend_
# ingredients.py/recommend_recipes.py via recommendation_scoring.
# score_candidate's carbon_tier — see carbon_footprint.py's module
# docstring for how and why it's deliberately modest/gated.
VALID_GOALS = {
    "protein_quality", "nutrient_gaps", "budget", "exploring",
    "weight_loss", "visceral_fat_reduction",
    "longevity", "athletic_stamina", "athletic_strength", "athletic_power",
    "reduce_carbon_footprint",
}


def load_goal_keys(db: Session, profile: Profile) -> list[str]:
    """A profile's active goal keys, highest priority first."""
    rows = (
        db.query(ProfileGoal)
        .filter(ProfileGoal.profile_id == profile.id)
        .order_by(ProfileGoal.priority)
        .all()
    )
    return [r.goal for r in rows]


def load_goal_keys_batch(db: Session, profile_ids: list[int]) -> dict[int, list[str]]:
    """Same as load_goal_keys, batched for a list of profiles (e.g.
    GET /api/profiles listing every profile on an account) — one query
    regardless of how many profiles are being rendered."""
    if not profile_ids:
        return {}
    rows = (
        db.query(ProfileGoal)
        .filter(ProfileGoal.profile_id.in_(profile_ids))
        .order_by(ProfileGoal.profile_id, ProfileGoal.priority)
        .all()
    )
    by_profile_id: dict[int, list[str]] = {pid: [] for pid in profile_ids}
    for row in rows:
        by_profile_id[row.profile_id].append(row.goal)
    return by_profile_id


def attach_goals(db: Session, profile: Profile) -> Profile:
    """Attaches the profile's real goal set as a transient (unmapped)
    `goals` attribute — both what `schemas.ProfileOut.goals` reads via
    from_attributes, and what `goal_keys_of()` below reads so pure
    profile-only helpers (energy_goal.py) that don't have their own db
    session can see the full multi-goal set without a signature change
    threaded through their whole call graph."""
    profile.goals = load_goal_keys(db, profile)
    return profile


def goal_keys_of(profile: Profile) -> list[str]:
    """The profile's active goal keys — from attach_goals() if that was
    called on this instance, otherwise a defensive fallback to the legacy
    single-goal column. The fallback matters because a lot of existing
    test fixtures construct `Profile(goal=...)` directly, with no
    `ProfileGoal` rows and never routed through attach_goals()."""
    goals = getattr(profile, "goals", None)
    if goals is not None:
        return goals
    return [profile.goal] if profile.goal else []


def goal_weight(rank: int) -> float:
    """1-indexed priority rank -> relative scoring weight. See module
    docstring for the 1/rank policy."""
    return 1.0 / rank


def replace_goals(db: Session, profile: Profile, goals: list[str]) -> None:
    """Full-replace a profile's goal set (order = priority, 1-indexed) and
    keep the legacy `Profile.goal` mirror in sync with whatever is now
    priority 1 — used by both create_profile and update_profile so the
    two never drift apart. Does not commit; caller controls the
    transaction (both endpoints commit the rest of the profile in the
    same call)."""
    db.query(ProfileGoal).filter(ProfileGoal.profile_id == profile.id).delete(synchronize_session=False)
    # dedupe while preserving first-occurrence order — a repeated goal in
    # the input has no meaningful second priority slot to occupy
    seen: set[str] = set()
    ordered_unique = []
    for g in goals:
        if g not in seen:
            seen.add(g)
            ordered_unique.append(g)
    for i, g in enumerate(ordered_unique):
        db.add(ProfileGoal(profile_id=profile.id, goal=g, priority=i + 1))
    profile.goal = ordered_unique[0] if ordered_unique else None
