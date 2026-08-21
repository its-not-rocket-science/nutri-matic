"""PROMPT 4 of the phytate/mineral-bioavailability extension (see
prompts.txt) — a source-licence policy, separate from app.entitlements.

app.entitlements.FEATURE_ENTITLEMENTS answers "which *plan* gets which
*product feature*", and its own docstring says a missing entry there
defaults to universally available — the right default for a forgotten
product-feature flag, and the wrong one for copyright/licensing, where
the safe default is the opposite: unknown means refused, not granted.
This module is deliberately separate rather than a new
FEATURE_ENTITLEMENTS entry, and never consults User.plan at all — a
paid/professional/enterprise account gets exactly the same allow/deny
outcome as a free account on every surface, because this question
("is this data source legally usable here") has nothing to do with
which plan a user is on.

Surface keys are deliberately explicit, not a paid/free boolean —
prompts.txt's own list of eight (see SURFACE_* constants below). A
boolean can't distinguish "the ordinary personal UI" from "an Enterprise
batch job" from "an internal research script", and this policy needs to
allow the first while refusing the second and third stays context-
dependent (internal_research_or_admin is allowed; enterprise_batch is
not) in a way a single flag can't express.

Enforcement boundary: `require_surface` is a FastAPI dependency factory
(same convention as app.entitlements.require_feature) for any future
phytate router; `load_compound_observations` is the mandatory query
boundary every *reading* service must call instead of querying
CompoundObservation directly (see test_source_licence_policy_boundary.py
for the repository-level test that any new bare
`db.query(CompoundObservation)` outside this module's own allowlist is
a failing test, not a silent gap). The writing side (ingest_phytate.py,
import_reviewed_phytate_mappings.py, resolve_phytate_stable_ids.py) is
out of scope here — those already fail closed on their own licensing gate
(--scope) and never serve a response to an end user.

Activation procedure for a future FAO reply (documented, not
implemented): when Paul provides FAO's actual written terms, (1) record
them in docs/phytate-evidence-review.md first, (2) only then edit
PHYFOODCOMP_1_0's `licence_status`/`permitted_surfaces`/
`redistribution_permitted`/`export_permitted` here to match those exact
terms — never flip licence_status to granted because a generic
"commercial use enabled" environment flag was set elsewhere; this module
has no such flag and must not gain one that a generic production
setting can trip.
"""

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from .models import CompoundObservation

SURFACE_PERSONAL_FREE_UI = "personal_free_ui"
SURFACE_PERSONAL_FREE_INTERNAL_API = "personal_free_internal_api"
SURFACE_PUBLIC_API = "public_api"
SURFACE_PROFESSIONAL_DASHBOARD = "professional_dashboard"
SURFACE_CLINICIAN_REPORT = "clinician_report"
SURFACE_ENTERPRISE_BATCH = "enterprise_batch"
SURFACE_PAID_EXPORT = "paid_export"
SURFACE_INTERNAL_RESEARCH_OR_ADMIN = "internal_research_or_admin"

KNOWN_SURFACES = frozenset({
    SURFACE_PERSONAL_FREE_UI,
    SURFACE_PERSONAL_FREE_INTERNAL_API,
    SURFACE_PUBLIC_API,
    SURFACE_PROFESSIONAL_DASHBOARD,
    SURFACE_CLINICIAN_REPORT,
    SURFACE_ENTERPRISE_BATCH,
    SURFACE_PAID_EXPORT,
    SURFACE_INTERNAL_RESEARCH_OR_ADMIN,
})

PHYFOODCOMP_1_0 = "phyfoodcomp_1_0"

LICENCE_STATUS_PENDING = "pending_commercial_permission"
LICENCE_STATUS_GRANTED = "commercial_permission_granted"  # not used yet — see module docstring


class SourceLicenceError(PermissionError):
    """Raised for any unknown source, unknown surface, or a surface this
    source's policy doesn't explicitly permit. Callers must let this
    propagate (typically into a 403) rather than catch-and-continue."""


@dataclass(frozen=True)
class SourceLicencePolicy:
    source_key: str
    licence_status: str
    permitted_surfaces: frozenset[str]
    prohibited_surfaces: frozenset[str]
    attribution_required: bool
    attribution_text: str
    source_name: str
    source_version: str
    methodology_version: str
    redistribution_permitted: bool
    export_permitted: bool
    licence_request_date: date
    licence_request_status: str
    audit_note: str


# The only source registered so far. licence_status/permitted_surfaces
# are deliberately conservative: only the ordinary free personal surface
# and internal research/admin use are permitted while FAO's reply is
# pending (prompts.txt PROMPT 4) — every paid/professional/enterprise/
# public-API/export surface is explicit in prohibited_surfaces, not just
# absent from permitted_surfaces, so the intent reads as a decision, not
# an oversight.
SOURCE_LICENCE_POLICIES: dict[str, SourceLicencePolicy] = {
    PHYFOODCOMP_1_0: SourceLicencePolicy(
        source_key=PHYFOODCOMP_1_0,
        licence_status=LICENCE_STATUS_PENDING,
        permitted_surfaces=frozenset({
            SURFACE_PERSONAL_FREE_UI,
            SURFACE_PERSONAL_FREE_INTERNAL_API,
            SURFACE_INTERNAL_RESEARCH_OR_ADMIN,
        }),
        prohibited_surfaces=frozenset({
            SURFACE_PUBLIC_API,
            SURFACE_PROFESSIONAL_DASHBOARD,
            SURFACE_CLINICIAN_REPORT,
            SURFACE_ENTERPRISE_BATCH,
            SURFACE_PAID_EXPORT,
        }),
        attribution_required=True,
        attribution_text="FAO/INFOODS/IZiNCG. Global food composition database for phytate (PhyFoodComp), version 1.0.",
        source_name="PhyFoodComp1.0",
        source_version="1.0",
        methodology_version="unset — no selection/aggregation methodology exists yet (see prompts.txt PROMPT 6)",
        redistribution_permitted=False,
        export_permitted=False,
        licence_request_date=date(2026, 8, 16),
        licence_request_status="awaiting_fao_reply",
        audit_note=(
            "See docs/phytate-evidence-review.md for the full evidence/licence trail, including both the "
            "original email request and the 2026-08-16 formal licence-request-form submission."
        ),
    ),
}

# compound (CompoundObservation.compound) -> source_key. Generic across
# future compounds by construction, same reasoning as CompoundObservation
# itself: a later compound (oxalate, tannin) adds one line here, not a
# schema or enforcement change.
COMPOUND_SOURCE_KEYS: dict[str, str] = {
    "phytate": PHYFOODCOMP_1_0,
}


def get_policy(source_key: str) -> SourceLicencePolicy:
    policy = SOURCE_LICENCE_POLICIES.get(source_key)
    if policy is None:
        raise SourceLicenceError(
            f"no registered source-licence policy for source_key={source_key!r} — failing closed, refusing access"
        )
    return policy


def source_key_for_compound(compound: str) -> str:
    source_key = COMPOUND_SOURCE_KEYS.get(compound)
    if source_key is None:
        raise SourceLicenceError(
            f"no registered source_key for compound={compound!r} — failing closed, refusing access"
        )
    return source_key


def check_surface_allowed(source_key: str, surface: str) -> None:
    """Raises SourceLicenceError unless `surface` is explicitly permitted
    for `source_key`. Fails closed for an unrecognised surface string
    exactly like an unrecognised source — a typo'd surface key must never
    silently fall through to "allowed"."""
    if surface not in KNOWN_SURFACES:
        raise SourceLicenceError(f"unknown surface {surface!r} — failing closed, refusing access")
    policy = get_policy(source_key)
    if surface not in policy.permitted_surfaces:
        raise SourceLicenceError(
            f"source {source_key!r} (licence_status={policy.licence_status}) does not permit surface {surface!r}"
        )


def require_surface(source_key: str, surface: str):
    """FastAPI dependency factory, same convention as
    app.entitlements.require_feature — Depends(require_surface(
    PHYFOODCOMP_1_0, SURFACE_PERSONAL_FREE_UI)) on a future phytate
    router. Deliberately takes no `current_user`/plan parameter at all:
    this is a licensing gate, not a product-entitlement gate (see module
    docstring), so it cannot be influenced by which plan the caller is
    on even by accident."""

    def _check() -> None:
        try:
            check_surface_allowed(source_key, surface)
        except SourceLicenceError as e:
            raise HTTPException(status_code=403, detail=str(e)) from e

    return _check


def load_compound_observations(db: Session, compound: str, surface: str) -> Query:
    """The mandatory read boundary: any future service that serves
    CompoundObservation rows to a caller must build its query from this,
    not from `db.query(CompoundObservation)` directly — see
    test_source_licence_policy_boundary.py's repository-level test, which
    fails if a new bare query appears outside this module's own
    allowlist. Raises SourceLicenceError before the query is even built
    if `surface` isn't permitted for whichever source backs `compound`."""
    source_key = source_key_for_compound(compound)
    check_surface_allowed(source_key, surface)
    return db.query(CompoundObservation).filter(CompoundObservation.compound == compound)


def validate_source_licence_policy_coverage(db: Session) -> list[str]:
    """Returns a warning string for every distinct `compound` value
    actually present in compound_observations that has no
    COMPOUND_SOURCE_KEYS entry — a PhyFoodComp-shaped consumer added
    without a registered policy. Callable from an ops/health check or a
    CI job once a real compound-observation-serving consumer exists
    (none does yet — Prompt 6/7); deliberately not wired into app
    startup here, since querying the database at process-import time for
    a check with nothing yet to verify would add a boot-time DB
    dependency this app doesn't otherwise have (see app.main's existing
    validate_monitoring_config/validate_rate_limit_config, both
    DB-free)."""
    rows = db.query(CompoundObservation.compound).distinct().all()
    return [
        f"compound={compound!r} has no registered source_key in COMPOUND_SOURCE_KEYS — failing closed"
        for (compound,) in rows
        if compound not in COMPOUND_SOURCE_KEYS
    ]
