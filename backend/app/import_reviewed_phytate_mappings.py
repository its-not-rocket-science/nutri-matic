"""PROMPT 3 of the phytate/mineral-bioavailability extension (see
prompts.txt) — the one canonical reviewed PhyFoodComp ingestion command.
Extends the importer originally built to close the automated pipeline's
needs_review gate (see git history / PR history for the pre-Prompt-2
version of this file) so there is exactly one write path, not two.

Consumes, together, never separately:
  1. the real PhyFoodComp 1.0 workbook (outside git — see
     app.phyfoodcomp_adapter);
  2. the signed review decision set (the seven review_*.csv files);
  3. the stable-ID mapping app.resolve_phytate_stable_ids produced
     (docs/phytate-review/stable_id_mapping.csv), keyed on fdc_id, not
     just a local Food.id;
  4. the verified FDC catalogue manifest (app.catalogue_manifest);
  5. explicit dataset citation/version/access-date metadata, passed on
     the command line, never defaulted.

Licensing (prompts.txt PROMPT 10): --destination-surface is checked
against app.source_licence_policy.SOURCE_LICENCE_POLICIES via
check_surface_allowed in both dry-run and --apply modes -- the same
function the read boundary (require_surface/load_compound_observations)
uses, not a second parallel copy of the rule an earlier version of this
module kept (a plain --scope string checked only against a small
hard-coded set in this file, never actually consulting the policy
module at all). --apply additionally requires
check_deployment_permits_write, which also checks this deployment's own
DEPLOYMENT_PERMITTED_SURFACES environment configuration -- a CLI
operator's --destination-surface claim alone can never be sufficient to
authorise a write, since the CLI has no way to verify what the database
it's writing into will actually be used to serve. A successful --apply
records an immutable CompoundImportAuditRecord row in the same
transaction as the observations it accounts for; dry-run never writes
one, matching its own "never writes anything, ever" guarantee.

This module never imports app.stock_recipes.food_matching and never
calls match_ingredient — a reviewed observation's target comes only
from the stable-ID mapping (approve/replace) or is nulled (reject/
unresolved); it is never re-derived from a food name.

Reconciliation is two-phase by design: `reconcile_rows` computes a full,
deterministic report and the complete list of blocking problems (never
stopping at the first one, same convention as validate_and_consolidate)
*before* anything is written. Any blocking problem — an unknown,
missing, or duplicate row_identifier; a workbook value that disagrees
with the signed review record beyond VALUE_TOLERANCE; an approve/
replace row absent from the stable-ID mapping; a stable-ID target whose
Food.id no longer has the fdc_id the mapping recorded — refuses the
*entire* import, not just the offending row: `main()` never opens a
write transaction while `problems` is non-empty, and `apply_plans` is
never called in that case. That is this module's rollback guarantee —
there is no partial-apply path to roll back from in the first place.

CENSORED_ROW_AUTO_POLICY (documented manual action from prompts.txt
PROMPT 8's audit): the real PhyFoodComp workbook has 245 censored
observations (Prompt 5) whose row_identifier the seven signed
review_*.csv files have never seen -- the pre-Prompt-5 adapter never
gave a censored cell a RawObservation at all, so none of them ever went
through human food-matching review. Rather than block the entire import
on all 245 forever, an unreviewed row_identifier whose workbook
observation is itself censored (value is None) is auto-classified
verdict="unresolved" instead of raising a blocking problem -- justified
because a censored observation carries no number to match against a
mineral database in the first place (Prompt 6's selection service
excludes it from `selected` regardless of which Food it's matched to,
which is why it's never matched to one: matched_food_id stays NULL,
identical to a genuinely human-reviewed "unresolved" row). This is
counted separately in the reconciliation report
(auto_unresolved_censored) so it's always visible how many rows were
auto-handled versus actually reviewed by a human. An unreviewed
row_identifier whose observation DOES have a real number is still a
full blocking problem -- this policy never widens past exactly the
censored case it was written for. A row_identifier a human explicitly
looked at and deferred (a blank verdict with a DEFERRED/MOVED note,
tracked by validate_and_consolidate's `deferred` return value) gets a
distinct rationale ("reviewed but explicitly deferred") from one truly
absent from every review file ("no review coverage at all") -- "no
review coverage" would be a false claim about a row someone did see.
"""

import argparse
import csv
import hashlib
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .catalogue_manifest import compute_fdc_catalogue_manifest
from .database import SessionLocal
from .models import CompoundImportAuditRecord, CompoundObservation, Food
from .phyfoodcomp_adapter import load_phyfoodcomp_workbook
from .source_licence_policy import (
    PHYFOODCOMP_1_0,
    KNOWN_SURFACES,
    SourceLicenceError,
    check_deployment_permits_write,
    check_surface_allowed,
    get_policy,
)

COMPOUND = "phytate"

# Bump if the fields this importer records to CompoundImportAuditRecord
# ever change meaning -- same incompatible-fingerprint-versioning
# convention as catalogue_manifest.IMPORTER_VERSION and
# phytate_selection.POLICY_VERSION.
IMPORTER_VERSION = "phytate-reviewed-import-v1"

# Human-readable Decision.source_file label for a CENSORED_ROW_AUTO_
# POLICY synthetic decision -- display only. The actual "is this an
# auto-classified decision" check is Decision.is_auto_censored (a real
# typed field), never a comparison against this string -- a magic
# sentinel compared with `==` is exactly the kind of thing a future
# typo/reused value could get wrong silently.
AUTO_CENSORED_SOURCE_FILE = "<auto: censored, unreviewed>"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW_DIR = REPO_ROOT / "docs" / "phytate-review"
DEFAULT_STABLE_ID_MAPPING = DEFAULT_REVIEW_DIR / "stable_id_mapping.csv"

# All seven review files -- review_2 (entirely "unresolved" verdicts) is
# not in export_final_mapping.py's SOURCE_FILES since that script only
# cares about approve/replace, but this importer must clear/confirm
# needs_review for those rows too.
REVIEW_FILES = [
    "review_1_ambiguous.csv",
    "review_2_no_candidate.csv",
    "review_3_branded_low_confidence.csv",
    "review_4_special_cases.csv",
    "review_5_infant_flour_cluster.csv",
    "review_6_accepted_sample.csv",
    "review_6b_accepted_remainder.csv",
]

CLOSE_ANALOGUE_CONFIDENCE = 0.8
CATEGORY_PROXY_CONFIDENCE = 0.65

# Workbook values and review-record values both ultimately derive from
# the same source cell, but pass through independent float parses (an
# openpyxl read here, a csv.DictReader read for the review record) --
# this tolerance only absorbs float-repr noise from that double
# round-trip, not genuine data disagreement. 1e-6 relative (with a
# 1e-9 floor for values near zero) is far tighter than any plausible
# transcription error.
VALUE_TOLERANCE_RELATIVE = 1e-6
VALUE_TOLERANCE_FLOOR = 1e-9

@dataclass
class Decision:
    row_identifier: str
    verdict: str  # approve | replace | reject | unresolved
    approved_fdc_food: str
    candidate_data_type: str
    rationale: str
    source_file: str
    # the signed record's own account of what this row measured --
    # cross-checked against the workbook's parsed RawObservation in
    # reconcile_rows, never trusted to still match without checking.
    food_description: str
    compound_fraction: str
    value: float | None
    # True only for a CENSORED_ROW_AUTO_POLICY synthetic decision -- a
    # real typed field, not a magic sentinel compared against source_file
    # (a past version of this code did exactly that, and it's the kind of
    # thing a typo'd/reused sentinel could silently get wrong with no
    # test catching it -- see the rationale-mislabelling bot-review
    # finding this field replaces the fragile version of).
    is_auto_censored: bool = False


@dataclass(frozen=True)
class StableTarget:
    food_id: int
    fdc_id: int
    catalogue_checksum: str
    # The signed decision's approved_fdc_food at the time the stable-ID
    # mapping was generated -- cross-checked against the *current*
    # decision in reconcile_rows so a re-reviewed row (approved_fdc_food
    # changed after the mapping was resolved) is caught as stale instead
    # of silently importing against the old target.
    approved_fdc_food: str = ""


@dataclass
class RowPlan:
    row_identifier: str
    action: str  # insert | update | unchanged
    fields: dict
    existing_id: int | None = None


def load_review_rows(review_dir: Path) -> dict[str, list[dict]]:
    rows_by_file = {}
    for fname in REVIEW_FILES:
        with open(review_dir / fname, encoding="utf-8", newline="") as f:
            rows_by_file[fname] = list(csv.DictReader(f))
    return rows_by_file


class UnparsableValueError(ValueError):
    pass


def _parse_value(raw: str) -> float | None:
    """None means "blank -- this reviewed row has no number to
    cross-check", a legitimate and common case (reject/unresolved rows,
    or a censored cell). A non-blank string that still doesn't parse as
    a float is a different thing entirely -- a malformed signed value --
    and must not be silently downgraded to the same None, since that
    would silently disable _values_disagree's cross-check for this row
    instead of surfacing the bad data."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        raise UnparsableValueError(f"value {raw!r} is not a blank field or a valid number") from None


def validate_and_consolidate(
    rows_by_file: dict[str, list[dict]],
) -> tuple[dict[str, Decision], list[str], set[str]]:
    """Returns (row_identifier -> Decision, blocking errors, deferred
    row_identifiers). If errors is non-empty, the caller must not
    proceed. `deferred` is every row_identifier a human explicitly looked
    at and punted (a blank verdict with a DEFERRED/MOVED note) that never
    got a real decision anywhere else -- distinct from a row_identifier
    entirely absent from every review file. reconcile_rows uses this to
    give CENSORED_ROW_AUTO_POLICY an accurate rationale: "reviewed but
    deferred" is not the same claim as "no review coverage at all", and
    conflating them was a real provenance bug (a bot-review finding on
    PR #52's code review)."""
    errors = []

    all_verdicts: dict[str, list[tuple[str, str, str]]] = {}
    for fname, rows in rows_by_file.items():
        for row in rows:
            verdict = row["review_verdict"]
            if not verdict:
                continue
            rid = row["row_identifier"]
            all_verdicts.setdefault(rid, []).append((fname, verdict, row["candidate"]))

    decisions: dict[str, Decision] = {}
    deferred_candidates: set[str] = set()
    for fname, rows in rows_by_file.items():
        for row in rows:
            rid = row["row_identifier"]
            verdict = row["review_verdict"]
            notes = row.get("review_notes", "")
            superseded = "MOVED -- superseded" in notes

            if not verdict:
                if row.get("sampled_for_review", "YES") == "NO":
                    continue
                if "DEFERRED" not in notes and "MOVED" not in notes:
                    errors.append(f"{fname} {rid}: blank review_verdict with no DEFERRED/MOVED explanation")
                    continue
                deferred_candidates.add(rid)
                continue

            if verdict in ("approve", "replace"):
                if superseded:
                    continue
                if not row["reviewer"]:
                    errors.append(f"{fname} {rid}: verdict={verdict} but no reviewer sign-off")
                    continue
                if not row.get("match_scope", "").strip():
                    errors.append(f"{fname} {rid}: verdict={verdict} but match_scope is blank")
                    continue
                if not row["approved_fdc_food"].strip():
                    errors.append(f"{fname} {rid}: verdict={verdict} but approved_fdc_food is blank")
                    continue

                contradicted_by = [
                    f2 for f2, v2, c2 in all_verdicts.get(rid, [])
                    if f2 != fname and v2 == "reject" and c2 == row["candidate"]
                ]
                if contradicted_by:
                    errors.append(
                        f"{rid}: {fname}={verdict} contradicted by {contradicted_by[0]}=reject "
                        "for the same candidate, not flagged as superseded"
                    )
                    continue

                if rid in decisions and decisions[rid].verdict in ("approve", "replace"):
                    if decisions[rid].approved_fdc_food != row["approved_fdc_food"]:
                        errors.append(
                            f"{rid}: conflicting approved_fdc_food between "
                            f"{decisions[rid].source_file} and {fname}"
                        )
                    continue

                try:
                    parsed_value = _parse_value(row.get("value", ""))
                except UnparsableValueError as e:
                    errors.append(f"{fname} {rid}: {e}")
                    continue

                decisions[rid] = Decision(
                    row_identifier=rid, verdict=verdict, approved_fdc_food=row["approved_fdc_food"],
                    candidate_data_type=row.get("candidate_data_type", ""),
                    rationale=row.get("review_notes") or row.get("rejection_reason") or "",
                    source_file=fname,
                    food_description=row.get("food_description", ""),
                    compound_fraction=row.get("compound_fraction", ""),
                    value=parsed_value,
                )

            elif verdict in ("reject", "unresolved"):
                if superseded:
                    continue
                if rid not in decisions:
                    try:
                        parsed_value = _parse_value(row.get("value", ""))
                    except UnparsableValueError as e:
                        errors.append(f"{fname} {rid}: {e}")
                        continue
                    decisions[rid] = Decision(
                        row_identifier=rid, verdict=verdict, approved_fdc_food="",
                        candidate_data_type="",
                        rationale=row.get("rejection_reason") or row.get("review_notes") or "",
                        source_file=fname,
                        food_description=row.get("food_description", ""),
                        compound_fraction=row.get("compound_fraction", ""),
                        value=parsed_value,
                    )

    deferred = deferred_candidates - decisions.keys()
    return decisions, errors, deferred


def load_stable_id_mapping(path: Path) -> dict[str, StableTarget]:
    with open(path, encoding="utf-8", newline="") as f:
        return {
            row["row_identifier"]: StableTarget(
                food_id=int(row["food_id"]), fdc_id=int(row["fdc_id"]),
                catalogue_checksum=row["catalogue_checksum"],
                approved_fdc_food=row["approved_fdc_food"],
            )
            for row in csv.DictReader(f)
        }


def compute_file_checksum(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def check_apply_confirmation(
    confirm_dataset_version: str | None, dataset_version: str,
    confirm_workbook_checksum: str | None, actual_workbook_checksum: str,
) -> str | None:
    """The second explicit acknowledgement prompts.txt PROMPT 3 requires
    before --apply is allowed to write anything: the operator must repeat
    back the exact dataset version and the workbook's actual sha256, not
    just pass --apply. Returns an error message if either doesn't match,
    None if both do."""
    if confirm_dataset_version != dataset_version:
        return (
            f"--confirm-dataset-version ({confirm_dataset_version!r}) does not match "
            f"--dataset-version ({dataset_version!r}) -- refusing to apply"
        )
    if confirm_workbook_checksum != actual_workbook_checksum:
        return (
            f"--confirm-workbook-checksum ({confirm_workbook_checksum}) does not match the actual "
            f"workbook checksum ({actual_workbook_checksum}) -- refusing to apply"
        )
    return None


def check_catalogue_drift(stable_ids: dict[str, StableTarget], actual_checksum: str) -> str | None:
    """Returns an error message if the stable-ID mapping's recorded
    catalogue checksum(s) no longer match the live Food table, None if
    they're consistent (or there's nothing to compare -- an empty
    mapping has no checksum to drift from)."""
    recorded_checksums = {t.catalogue_checksum for t in stable_ids.values()}
    if recorded_checksums and recorded_checksums != {actual_checksum}:
        return (
            f"the Food catalogue has drifted since the stable-ID mapping was generated (mapping recorded "
            f"{sorted(recorded_checksums)}, current catalogue checksum is {actual_checksum}) -- re-run "
            "app.resolve_phytate_stable_ids against the current catalogue before importing."
        )
    return None


def _values_disagree(workbook_value: float | None, reviewed_value: float | None) -> bool:
    """Both censored (value=None) is not a disagreement -- nothing
    numeric to compare on either side. But numeric on one side and
    censored on the other IS a disagreement: the signed review record
    and the workbook cell disagree about whether this cell was even
    censored, which is exactly the kind of mismatch this check exists
    to catch, not a case to silently wave through."""
    if reviewed_value is None and workbook_value is None:
        return False
    if reviewed_value is None or workbook_value is None:
        return True
    tolerance = max(abs(reviewed_value) * VALUE_TOLERANCE_RELATIVE, VALUE_TOLERANCE_FLOOR)
    return abs(workbook_value - reviewed_value) > tolerance


def reconcile_rows(
    db: Session, rows: list, adapter_stats: dict, decisions: dict[str, Decision],
    stable_ids: dict[str, StableTarget], dataset_name: str, dataset_citation: str,
    dataset_version: str, access_date: date, deferred: set[str] = frozenset(),
) -> tuple[dict, list[str], list[RowPlan]]:
    """Computes the full deterministic reconciliation report plus every
    blocking problem across the whole workbook, without stopping at the
    first one -- see module docstring. Read-only: does not call
    db.add/db.commit."""
    report = {
        "source_observations": adapter_stats["rows_considered"],
        # observations_built counts numeric AND censored observations
        # together (see phyfoodcomp_adapter) -- subtract the censored
        # count so this key means what its name says, not a duplicate of
        # source_observations-minus-skips.
        "numeric_observations": adapter_stats["observations_built"] - adapter_stats["censored_observations_built"],
        "censored_observations": adapter_stats["censored_observations_built"],
        "approved": 0, "replaced": 0, "rejected": 0, "unresolved": 0,
        "inserted": 0, "updated": 0, "unchanged": 0, "blocked": 0, "unexpected": 0,
        "auto_unresolved_censored": 0,
    }
    problems: list[str] = []
    plans: list[RowPlan] = []
    seen_row_ids: set[str] = set()

    for row in rows:
        rid = row.row_identifier
        if rid is None:
            problems.append("workbook observation with no row_identifier -- cannot reconcile against review records")
            report["blocked"] += 1
            continue
        if rid in seen_row_ids:
            problems.append(f"{rid}: duplicate row_identifier within the workbook itself")
            report["blocked"] += 1
            continue
        seen_row_ids.add(rid)

        decision = decisions.get(rid)
        if decision is None and row.value is not None:
            problems.append(f"{rid}: no review verdict covers this row_identifier")
            report["blocked"] += 1
            continue
        if decision is None:
            # CENSORED_ROW_AUTO_POLICY (see module docstring) -- a
            # censored observation review has never seen is auto-
            # classified unresolved, not a blocking problem. Description/
            # fraction left blank (not copied from `row`) so the
            # disagreement checks below skip this decision via their own
            # existing falsy-guard, the same way they already do for any
            # human-reviewed decision that left those fields blank --
            # never a tautological check against the very row it came from.
            #
            # `deferred` distinguishes a row a human explicitly looked at
            # and punted (a blank verdict with a DEFERRED/MOVED note) from
            # one truly absent from every review file -- conflating them
            # was a real provenance bug (bot-review finding on PR #52):
            # "no review coverage" is a false claim about a row someone
            # did see.
            coverage_note = (
                "reviewed but explicitly deferred (see review_notes)" if rid in deferred
                else "no review coverage at all"
            )
            decision = Decision(
                row_identifier=rid, verdict="unresolved", approved_fdc_food="", candidate_data_type="",
                rationale=(
                    f"censored value, {coverage_note} -- auto-classified unresolved per "
                    "CENSORED_ROW_AUTO_POLICY (see module docstring): excluded from selection "
                    "regardless of food match, so food-matching review provides no scientific benefit"
                ),
                source_file=AUTO_CENSORED_SOURCE_FILE,
                food_description="", compound_fraction="", value=None,
                is_auto_censored=True,
            )
            report["auto_unresolved_censored"] += 1

        if decision.food_description and row.food_description != decision.food_description:
            problems.append(
                f"{rid}: workbook food_description {row.food_description!r} != "
                f"reviewed record {decision.food_description!r}"
            )
            report["blocked"] += 1
            continue
        if decision.compound_fraction and row.compound_fraction != decision.compound_fraction:
            problems.append(
                f"{rid}: workbook compound_fraction {row.compound_fraction!r} != "
                f"reviewed record {decision.compound_fraction!r}"
            )
            report["blocked"] += 1
            continue
        if _values_disagree(row.value, decision.value):
            problems.append(
                f"{rid}: workbook value {row.value} disagrees with reviewed record {decision.value} "
                f"beyond tolerance"
            )
            report["blocked"] += 1
            continue

        if decision.verdict in ("approve", "replace"):
            target = stable_ids.get(rid)
            if target is None:
                problems.append(
                    f"{rid}: verdict={decision.verdict} but not present in the resolved stable-ID mapping "
                    "-- run app.resolve_phytate_stable_ids first"
                )
                report["blocked"] += 1
                continue

            if target.approved_fdc_food != decision.approved_fdc_food:
                problems.append(
                    f"{rid}: stable-ID mapping was resolved against approved_fdc_food="
                    f"{target.approved_fdc_food!r}, but the signed decision now says "
                    f"{decision.approved_fdc_food!r} -- mapping is stale relative to a re-reviewed "
                    "decision, re-run app.resolve_phytate_stable_ids"
                )
                report["blocked"] += 1
                continue

            food = db.get(Food, target.food_id)
            if food is None or food.fdc_id != target.fdc_id:
                problems.append(
                    f"{rid}: stable-ID mapping says Food.id={target.food_id} has fdc_id={target.fdc_id}, "
                    f"but the database now has fdc_id={food.fdc_id if food else None} -- mapping is stale, "
                    "re-run the resolver"
                )
                report["blocked"] += 1
                continue

            matched_food_id = food.id
            if decision.verdict == "approve":
                match_relationship, confidence = "close_analogue", CLOSE_ANALOGUE_CONFIDENCE
                report["approved"] += 1
            else:
                match_relationship, confidence = "category_proxy", CATEGORY_PROXY_CONFIDENCE
                report["replaced"] += 1
        elif decision.verdict in ("reject", "unresolved"):
            matched_food_id = None
            match_relationship, confidence = "needs_review", None
            if decision.verdict == "reject":
                report["rejected"] += 1
            elif not decision.is_auto_censored:
                report["unresolved"] += 1
            # else: already counted via auto_unresolved_censored above --
            # every other bucket here is mutually exclusive, so this one
            # must not double-count the same row into both.
        else:
            problems.append(f"{rid}: decision verdict {decision.verdict!r} is not a recognised verdict")
            report["unexpected"] += 1
            continue

        if decision.is_auto_censored:
            # Never label a CENSORED_ROW_AUTO_POLICY decision "Human-reviewed" --
            # that would falsely claim human review provenance for a row no
            # reviewer ever saw (bot review finding on PR #52).
            rationale = f"Auto-classified (not human-reviewed, {decision.verdict}): {decision.rationale}"
        else:
            rationale = f"Human-reviewed ({decision.verdict}): {decision.rationale}"
        fields = dict(
            compound=COMPOUND, compound_fraction=row.compound_fraction, original_value=row.value,
            original_unit=row.unit, original_basis=row.basis,
            original_value_text=row.value_text, value_qualifier=row.value_qualifier,
            detection_limit_value=row.detection_limit_value, detection_limit_unit=row.detection_limit_unit,
            original_value_provenance=None if row.value is None else "source_reported",
            source_food_description=row.food_description,
            source_preparation_state=row.preparation_state, source_dataset_name=dataset_name,
            source_dataset_citation=dataset_citation, source_dataset_version=dataset_version,
            source_access_date=access_date, analytical_method=row.analytical_method,
            source_row_identifier=rid, match_relationship=match_relationship, match_confidence=confidence,
            match_rationale=rationale, matched_food_id=matched_food_id,
        )

        existing = (
            db.query(CompoundObservation)
            .filter(
                CompoundObservation.compound == COMPOUND,
                CompoundObservation.source_dataset_name == dataset_name,
                CompoundObservation.source_dataset_version == dataset_version,
                CompoundObservation.source_row_identifier == rid,
            )
            .one_or_none()
        )

        if existing is None:
            plans.append(RowPlan(row_identifier=rid, action="insert", fields=fields))
            report["inserted"] += 1
        else:
            changed = any(getattr(existing, key) != value for key, value in fields.items())
            if changed:
                plans.append(RowPlan(row_identifier=rid, action="update", fields=fields, existing_id=existing.id))
                report["updated"] += 1
            else:
                plans.append(RowPlan(row_identifier=rid, action="unchanged", fields=fields, existing_id=existing.id))
                report["unchanged"] += 1

    missing_from_workbook = decisions.keys() - seen_row_ids
    for rid in sorted(missing_from_workbook):
        problems.append(
            f"{rid}: has a signed review decision but no matching row_identifier in the workbook "
            "-- the review file is stale relative to the workbook actually being imported"
        )
        report["blocked"] += 1

    return report, problems, plans


def apply_plans(db: Session, plans: list[RowPlan]) -> None:
    """Writes every non-blocked plan. Caller is responsible for only
    calling this when `problems` from reconcile_rows is empty, and for
    committing/rolling back the surrounding transaction."""
    for plan in plans:
        if plan.action == "insert":
            db.add(CompoundObservation(**plan.fields))
        elif plan.action == "update":
            existing = db.get(CompoundObservation, plan.existing_id)
            for key, value in plan.fields.items():
                setattr(existing, key, value)
        # "unchanged" -- nothing to write


def print_report(report: dict) -> None:
    for key in (
        "source_observations", "numeric_observations", "censored_observations",
        "approved", "replaced", "rejected", "unresolved", "auto_unresolved_censored",
        "inserted", "updated", "unchanged", "blocked", "unexpected",
    ):
        print(f"{key}: {report[key]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx", required=True, help="Path to the real PhyFoodComp_1.0.xlsx (kept outside git)")
    parser.add_argument("--review-dir", default=str(DEFAULT_REVIEW_DIR))
    parser.add_argument("--stable-id-mapping", default=str(DEFAULT_STABLE_ID_MAPPING))
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--dataset-citation", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--access-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--destination-surface", required=True, choices=sorted(KNOWN_SURFACES),
        help="Which app.source_licence_policy surface this run's data is destined for -- checked against "
             "SOURCE_LICENCE_POLICIES (same rule the read boundary enforces, not a separate copy of it) and, "
             "with --apply, against this deployment's own DEPLOYMENT_PERMITTED_SURFACES configuration too.",
    )
    parser.add_argument("--apply", action="store_true", help="Without this, always a dry run (the default).")
    parser.add_argument(
        "--confirm-dataset-version", default=None,
        help="Required with --apply: must exactly repeat --dataset-version, as an explicit second "
             "acknowledgement of what is about to be imported.",
    )
    parser.add_argument(
        "--confirm-workbook-checksum", default=None,
        help="Required with --apply: must exactly match the sha256 of the --xlsx file being imported.",
    )
    args = parser.parse_args()

    # Checked in both dry-run and --apply modes -- dry-run stays available
    # for any currently-permitted surface (including
    # internal_research_or_admin, prompts.txt PROMPT 10 requirement 1),
    # since it never writes regardless of which surface was declared.
    try:
        check_surface_allowed(PHYFOODCOMP_1_0, args.destination_surface)
    except SourceLicenceError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    xlsx_path = Path(args.xlsx)
    if not xlsx_path.is_file():
        print(f"error: not a file: {xlsx_path}", file=sys.stderr)
        sys.exit(1)
    review_dir = Path(args.review_dir)
    stable_id_mapping_path = Path(args.stable_id_mapping)
    if not stable_id_mapping_path.is_file():
        print(
            f"error: not a file: {stable_id_mapping_path} -- run app.resolve_phytate_stable_ids first",
            file=sys.stderr,
        )
        sys.exit(1)

    access_date = datetime.strptime(args.access_date, "%Y-%m-%d").date()
    workbook_checksum = compute_file_checksum(xlsx_path)

    rows, adapter_stats = load_phyfoodcomp_workbook(xlsx_path)
    print(
        f"parsed workbook: sheets={adapter_stats['sheets']} rows_considered={adapter_stats['rows_considered']} "
        f"rows_skipped_no_description={adapter_stats['rows_skipped_no_description']} "
        f"censored_observations_built={adapter_stats['censored_observations_built']} "
        f"observations_built={adapter_stats['observations_built']}"
    )

    rows_by_file = load_review_rows(review_dir)
    decisions, errors, deferred = validate_and_consolidate(rows_by_file)
    if errors:
        print(f"ERROR: {len(errors)} blocking problem(s) in the review files -- refusing to import:", file=sys.stderr)
        for e in errors[:30]:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    stable_ids = load_stable_id_mapping(stable_id_mapping_path)

    db = SessionLocal()
    try:
        try:
            db.execute(text("SELECT 1 FROM compound_observations LIMIT 1"))
        except Exception:
            print(
                "ERROR: compound_observations table not found -- run the reviewed Alembic migrations "
                "(alembic upgrade head) first. This importer never calls Base.metadata.create_all.",
                file=sys.stderr,
            )
            sys.exit(1)

        actual_manifest = compute_fdc_catalogue_manifest(db)
        drift_error = check_catalogue_drift(stable_ids, actual_manifest.catalogue_snapshot_checksum)
        if drift_error:
            print(f"ERROR: {drift_error}", file=sys.stderr)
            sys.exit(1)

        report, problems, plans = reconcile_rows(
            db, rows, adapter_stats, decisions, stable_ids,
            args.dataset_name, args.dataset_citation, args.dataset_version, access_date,
            deferred=deferred,
        )
        print_report(report)

        if problems:
            print(f"\n{len(problems)} blocking problem(s) -- refusing to import:", file=sys.stderr)
            for p in problems[:30]:
                print(f"  {p}", file=sys.stderr)
            sys.exit(1)

        if not args.apply:
            print("\n(dry run -- no changes committed; pass --apply plus both --confirm-* flags to write)")
            return

        confirmation_error = check_apply_confirmation(
            args.confirm_dataset_version, args.dataset_version, args.confirm_workbook_checksum, workbook_checksum,
        )
        if confirmation_error:
            print(f"ERROR: {confirmation_error}", file=sys.stderr)
            sys.exit(1)

        # The write-path-specific check (prompts.txt PROMPT 10): unlike
        # check_surface_allowed above, this also requires the deployment's
        # own DEPLOYMENT_PERMITTED_SURFACES configuration to declare
        # destination_surface -- an operator's flag alone is never
        # sufficient to authorise an actual write. Checked only here, not
        # for dry-run, since dry-run never writes regardless.
        try:
            check_deployment_permits_write(PHYFOODCOMP_1_0, args.destination_surface)
        except SourceLicenceError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            apply_plans(db, plans)
            # The immutable audit row lives in the same transaction as the
            # observations it accounts for -- a rollback below undoes both
            # together, and a successful commit never lacks one. See
            # CompoundImportAuditRecord's own docstring for why this is
            # never written on a dry run.
            db.add(CompoundImportAuditRecord(
                compound=COMPOUND,
                source_key=PHYFOODCOMP_1_0,
                dataset_version=args.dataset_version,
                licence_status_at_import=get_policy(PHYFOODCOMP_1_0).licence_status,
                destination_surface=args.destination_surface,
                workbook_checksum=workbook_checksum,
                catalogue_checksum=actual_manifest.catalogue_snapshot_checksum,
                importer_version=IMPORTER_VERSION,
                operator_confirmed_dataset_version=args.confirm_dataset_version,
                operator_confirmed_workbook_checksum=args.confirm_workbook_checksum,
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"\nApplied: {report['inserted']} inserted, {report['updated']} updated, "
              f"{report['unchanged']} unchanged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
