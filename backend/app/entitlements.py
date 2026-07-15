"""Entitlement primitive — Phase 3.1 of nutri-matic-claude-prompts.txt.

Deliberately minimal: just enough that a request or user can be checked
against a named feature, so later commercial work (Prompt 3.2's API
platform, Phase 4's tiers) has something real to hook into. Explicitly
NOT built here: tier UI, billing, upgrade flows, payment integration — see
the prompt file's own instruction not to build those yet.

Plans are plain strings, not a closed enum or DB-level constraint — adding
"educational" or "enterprise" later (Phase 4) is just a new string constant
and a new entry in FEATURE_ENTITLEMENTS below, not a migration or a
rewrite of anything that checks entitlements.

FEATURE_ENTITLEMENTS is the single source of truth for "which plans get
which features" — a data table, not scattered if-checks, so the whole
policy is readable in one place (same pattern as nutrients.py's NUTRIENTS
dict or digestibility_reference.py's rule tables elsewhere in this
codebase). No feature keys are actually enforced anywhere yet — this
module is the primitive, not a statement that any current endpoint is
gated. The transparency/provenance layer (measured-vs-estimated labelling,
methodology_version, the Data & Methodology page) must never appear here:
see nutri-matic-claude-prompts.txt's ground rules and Phase 4.1's explicit
"stays free forever" list.
"""

from datetime import date, datetime, timezone

from fastapi import Depends, HTTPException

from .auth import get_current_user
from .models import User

PLAN_FREE = "free"
PLAN_TRIAL = "trial"  # trial of PLAN_PAID (Pro) specifically — see docs/tiered-commercial-model.md
PLAN_PAID = "paid"  # "Pro" in docs/tiered-commercial-model.md — the self-serve paid tier
PLAN_PROFESSIONAL = "professional"  # docs/tiered-commercial-model.md's "Professional" tier
PLAN_ENTERPRISE = "enterprise"  # docs/tiered-commercial-model.md's "Enterprise" tier

# Every plan a user's `plan` column is expected to hold today. Extend this
# (and FEATURE_ENTITLEMENTS below) when a new plan type is introduced —
# never repurpose an existing value's meaning.
KNOWN_PLANS = {PLAN_FREE, PLAN_TRIAL, PLAN_PAID, PLAN_PROFESSIONAL, PLAN_ENTERPRISE}

# feature key -> set of plans that include it. A feature with no entry
# here is available to everyone (the safe default — a typo'd/forgotten
# feature key fails open to "available", not closed to "blocked", so a
# missing table entry can't accidentally lock out free users from
# something that was never meant to be gated).
FEATURE_ENTITLEMENTS: dict[str, set[str]] = {}

# Phase 4.4 product-led growth review (docs/product-led-growth-review.md):
# both usage caps below are tied to a real, scaling infrastructure cost
# (storage rows / API request volume), not an artificial lock on
# functionality that costs nothing extra to provide — see that doc for the
# full reasoning on why these two were gated and others weren't.

# Diary snapshots (Phase 2.3) — each one persists a full computed summary
# as a JSON row (DiarySnapshot.summary_json), a genuine, scaling storage
# cost unlike most of this app's compute-on-demand features.
FREE_TIER_SNAPSHOT_LIMIT = 5

# Public API (Phase 3.2) request quota, applied at key-creation time (see
# routers/api_keys.py::create_api_key) — existing keys keep their quota
# even if the owner's plan changes later; create a new key to pick up a
# new plan's quota. Real infra cost (request volume), same reasoning as
# the snapshot cap above.
API_QUOTA_BY_PLAN: dict[str, int] = {
    PLAN_FREE: 100,
    PLAN_TRIAL: 500,
    PLAN_PAID: 5_000,
    PLAN_PROFESSIONAL: 20_000,
    PLAN_ENTERPRISE: 100_000,
}
DEFAULT_API_QUOTA = API_QUOTA_BY_PLAN[PLAN_FREE]


def effective_plan(user: User, *, today: date | None = None) -> str:
    """The plan that actually applies right now — a lapsed trial reads as
    "free" without needing a background job or a database write to
    downgrade it. `today` is injectable for tests; defaults to the real
    current date."""
    if user.plan == PLAN_TRIAL:
        if user.plan_expires_at is None:
            return PLAN_TRIAL
        now = datetime.now(timezone.utc) if today is None else datetime.combine(today, datetime.min.time(), timezone.utc)
        if now > user.plan_expires_at:
            return PLAN_FREE
    return user.plan


def user_has_feature(user: User, feature: str) -> bool:
    allowed_plans = FEATURE_ENTITLEMENTS.get(feature)
    if allowed_plans is None:
        return True
    return effective_plan(user) in allowed_plans


def require_feature(feature: str):
    """FastAPI dependency factory: Depends(require_feature("some_feature"))
    on any router, chained after get_current_user like any other
    dependency. 403s with a message naming the feature and the user's
    actual plan, rather than a generic "forbidden" — this is a primitive
    for future paid endpoints to use, not currently applied to any
    existing route."""

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_feature(current_user, feature):
            raise HTTPException(
                status_code=403,
                detail=f"'{feature}' requires a plan that includes it (current plan: {effective_plan(current_user)})",
            )
        return current_user

    return _check
