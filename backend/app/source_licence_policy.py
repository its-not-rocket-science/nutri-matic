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
(same convention as app.entitlements.require_feature), used by
app.routers.phytate, today's real phytate consumer;
`load_compound_observations` is the mandatory query boundary every
*reading* service must call instead of querying CompoundObservation
directly (see test_source_licence_policy_boundary.py for the
repository-level test that any new bare `db.query(CompoundObservation)`
outside this module's own allowlist is a failing test, not a silent
gap). `validate_source_licence_policy_coverage` (PROMPT 13) is a
supplementary operational check, wired into
GET /api/ready/licence-policy-coverage — it can only catch a
misconfiguration before a real request exercises it; it is never itself
the enforcement point.

The writing side (import_reviewed_phytate_mappings.py) also consults this
module now (prompts.txt PROMPT 10) via `check_surface_allowed` — the
same function the read boundary uses, not a second parallel copy of the
rules — plus `check_deployment_permits_write`, a second, independent
check that a CLI operator's own --destination-surface claim cannot
satisfy alone (see that function's docstring for why). Before PROMPT 10,
the importer's --scope flag only checked itself against a small
hard-coded set duplicated in that file; it never actually consulted this
module at all, despite an earlier version of this docstring claiming
otherwise. Read-time enforcement (`require_surface`/
`load_compound_observations`) remains the ultimate enforcement point
regardless of what any import recorded — a wrong or stale
destination_surface on an old CompoundImportAuditRecord row can never
by itself make a prohibited surface start being served.

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

import os
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Query, Session

from .models import CompoundObservation

# prompts.txt PROMPT 10: which surfaces *this deployment's database* is
# actually provisioned to serve, comma-separated (e.g.
# "personal_free_ui,personal_free_internal_api"). Deliberately a second,
# independent signal from whatever an import operator types on the
# command line -- a CLI import command has no way to know what the
# database it's writing into will actually be used to serve later, so an
# operator's --destination-surface claim alone is not allowed to be the
# only thing standing between a write and a prohibited surface. See
# check_deployment_permits_write.
DEPLOYMENT_SURFACES_ENV_VAR = "DEPLOYMENT_PERMITTED_SURFACES"

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

# (CompoundObservation.compound, CompoundObservation.source_dataset_name)
# -> source_key. Keyed on the pair, not compound alone: `compound` only
# says what was measured, not which dataset measured it (PROMPT 13) — a
# future second phytate source with a different source_dataset_name must
# never silently inherit PhyFoodComp's policy just because it shares the
# compound name "phytate". Generic across future compounds by
# construction, same reasoning as CompoundObservation itself: a later
# compound (oxalate, tannin) adds one line here, not a schema or
# enforcement change.
COMPOUND_SOURCE_KEYS: dict[tuple[str, str], str] = {
    ("phytate", "PhyFoodComp1.0"): PHYFOODCOMP_1_0,
}


def get_policy(source_key: str) -> SourceLicencePolicy:
    policy = SOURCE_LICENCE_POLICIES.get(source_key)
    if policy is None:
        raise SourceLicenceError(
            f"no registered source-licence policy for source_key={source_key!r} — failing closed, refusing access"
        )
    return policy


def source_key_for_compound(compound: str) -> str:
    """Looks up the single registered source_key for `compound` across
    every (compound, source_dataset_name) pair in COMPOUND_SOURCE_KEYS.
    Fails closed both when no pair matches and when more than one does —
    the latter means two distinct datasets both report this compound and
    nothing here can safely guess which one a caller who only supplied a
    compound name (not a dataset name) actually means. That ambiguity
    itself is the PROMPT 13 safeguard: a second phytate source registered
    without updating every compound-only call site turns into an
    explicit failure here, never a silent fall-through to whichever
    policy happens to be checked first."""
    matches = {source_key for (c, _sdn), source_key in COMPOUND_SOURCE_KEYS.items() if c == compound}
    if not matches:
        raise SourceLicenceError(
            f"no registered source_key for compound={compound!r} — failing closed, refusing access"
        )
    if len(matches) > 1:
        raise SourceLicenceError(
            f"compound={compound!r} has {len(matches)} distinct registered source_keys "
            f"({sorted(matches)}) — ambiguous, failing closed, refusing access"
        )
    return matches.pop()


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


def deployment_permitted_surfaces() -> frozenset[str]:
    """The surfaces this deployment's own environment configuration
    declares it is provisioned to serve. Unset or empty means no
    surfaces are declared -- fails closed, never "assume everything" and
    never "assume the same as whatever SOURCE_LICENCE_POLICIES currently
    permits" (a deployment must explicitly opt in, not inherit a default
    that could later widen without this specific deployment's operator
    ever deciding that)."""
    raw = os.environ.get(DEPLOYMENT_SURFACES_ENV_VAR, "")
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def check_deployment_permits_write(source_key: str, surface: str) -> None:
    """Raises SourceLicenceError unless BOTH: (a) `surface` is currently
    permitted by SOURCE_LICENCE_POLICIES for `source_key` (delegates to
    check_surface_allowed -- the exact same check the read boundary uses,
    not a duplicated copy of the rule), and (b) this deployment's own
    DEPLOYMENT_PERMITTED_SURFACES environment configuration explicitly
    lists `surface`.

    (b) is the write-path-specific addition prompts.txt PROMPT 10 asked
    for: an import CLI has no way to verify what the database it's about
    to write into will actually be used to serve. Without a second,
    deployment-level signal, an operator who mistypes
    --destination-surface, or who runs the same command against a
    database that's wired up differently than they assume, has nothing
    stopping the write except their own claim being accidentally
    correct. This is defense in depth, not the primary safety net --
    require_surface/load_compound_observations at *read* time remain the
    enforcement point that actually decides whether a prohibited surface
    can ever be served, regardless of what any past import recorded."""
    check_surface_allowed(source_key, surface)
    permitted = deployment_permitted_surfaces()
    if surface not in permitted:
        raise SourceLicenceError(
            f"this deployment's {DEPLOYMENT_SURFACES_ENV_VAR} does not list surface {surface!r} "
            f"(currently declares: {sorted(permitted) or 'nothing -- unset or empty'}) -- refusing to "
            "write data for a surface this deployment hasn't explicitly declared it serves"
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
    if `surface` isn't permitted for whichever source backs `compound`.

    Also filters on source_dataset_name == policy.source_name, not just
    `compound` -- `compound` alone only tells you what was measured, not
    which dataset measured it. A future second source for the same
    compound name (a different phytate dataset with looser terms, say)
    would otherwise have its rows authorized under PhyFoodComp's policy
    just because COMPOUND_SOURCE_KEYS keys on compound, not on the
    combination actually stored on each row."""
    source_key = source_key_for_compound(compound)
    check_surface_allowed(source_key, surface)
    policy = get_policy(source_key)
    return db.query(CompoundObservation).filter(
        CompoundObservation.compound == compound,
        CompoundObservation.source_dataset_name == policy.source_name,
    )


def validate_source_licence_policy_coverage(db: Session) -> list[str]:
    """Returns a problem string for every distinct (compound,
    source_dataset_name) pair actually present in compound_observations
    that either:

      - has no COMPOUND_SOURCE_KEYS entry at all — a consumer added
        without a registered policy (this now includes a *second*,
        differently-named source for an already-registered compound:
        keying on the pair rather than compound alone means it is
        evaluated on its own, not silently covered by the first
        source's registration — PROMPT 13 requirement 3); or

      - has a registered policy whose `prohibited_surfaces` overlaps
        this deployment's own `deployment_permitted_surfaces()` — the
        environment is configured to serve a surface this compound's
        source explicitly forbids. `check_surface_allowed`/
        `require_surface` already refuse this at request time
        regardless (see module docstring: read-time enforcement is the
        ultimate authority), so this can only ever flag a
        misconfiguration before it's exercised by a real request, never
        substitute for that enforcement.

    Wired into GET /api/ready/licence-policy-coverage (app.routers.health)
    now that app.routers.phytate/app.phytate_selection are real
    CompoundObservation-serving consumers — deliberately still not called
    at process-import time (see app.main's existing
    validate_monitoring_config/validate_rate_limit_config, both DB-free):
    a per-request readiness check can report "not ready" cleanly, while a
    failed query at import time would just crash the process outright."""
    rows = db.query(CompoundObservation.compound, CompoundObservation.source_dataset_name).distinct().all()
    permitted = deployment_permitted_surfaces()
    problems: list[str] = []
    for compound, source_dataset_name in rows:
        source_key = COMPOUND_SOURCE_KEYS.get((compound, source_dataset_name))
        if source_key is None:
            problems.append(
                f"compound={compound!r} source_dataset_name={source_dataset_name!r} has no registered "
                "source_key in COMPOUND_SOURCE_KEYS — failing closed"
            )
            continue
        policy = get_policy(source_key)
        exposed = permitted & policy.prohibited_surfaces
        if exposed:
            problems.append(
                f"compound={compound!r} source_key={source_key!r} would be exposed on prohibited "
                f"surface(s) {sorted(exposed)} by this deployment's {DEPLOYMENT_SURFACES_ENV_VAR} — "
                "failing closed"
            )
    return problems
