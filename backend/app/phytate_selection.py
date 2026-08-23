"""PROMPT 6 of the phytate/mineral-bioavailability extension (see
prompts.txt) — a conservative, versioned, deterministic service that
selects which phytate CompoundObservation rows are usable for a given
food. Not an absorption model, and not a molar-ratio calculator (see
module bottom) — this is scope-limited to "what does the reviewed
literature actually say for this food, and is it safe to report."

Scientific constraints this module exists to enforce structurally, not
just document (prompts.txt PROMPT 6):
  - PHYTC* (phytic acid, by various analytical methods), PPI/PPD/PP-
    (phytate-phosphorus), and the inositol-phosphate tags (IP3..IP6,
    IP5_A_IP6, IP4_A_IP5_A_IP6, IPSUM) are three different quantities,
    not automatically interchangeable — see FRACTION_FAMILY. Observations
    from different families are always returned as separate entries in
    `selected`, never merged/averaged/compared into one number.
  - Overlapping individual and already-summed inositol-phosphate
    fractions are never summed — see SUBSUMES: a broader summed tag
    present for a food (e.g. IPSUM) makes the narrower tags it already
    includes (IP6, IP5_A_IP6, ...) redundant for further arithmetic, so
    those are moved to `declined` with an explicit reason rather than
    silently double-counted or silently dropped.
  - Different analytical methods within the same family (e.g. PHYTCPPI
    vs PHYTCPP, both phytic acid) are never blindly averaged — every
    distinct method present is kept as its own entry in `selected`.
  - A food whose only observations are censored (see app.models.
    CompoundObservation.value_qualifier, Prompt 5) has no usable number:
    status="insufficient_data", never a fabricated 0 or silently omitted
    coverage.

Every entry point requires `surface` and resolves observations through
app.source_licence_policy.load_compound_observations — the same
mandatory read boundary Prompt 4 built, so this service structurally
cannot be called under a prohibited surface (public_api,
professional_dashboard, clinician_report, enterprise_batch, paid_export)
while FAO permission remains pending; SourceLicenceError propagates to
the caller exactly like calling the boundary directly.

Deliberately NOT built here, per prompts.txt PROMPT 6's own scope
boundary: an absorption model, and phytate:zinc/phytate:iron molar
ratios (prompts.txt phrases that "if implementing" — not implemented in
this PR; it would need meal-level aggregation, an explicit equation
shown to the caller, and a decision to decline when inputs are missing
or incompatible, which is real design work for a future PR, not a
same-prompt add-on). Nothing here touches Nutri-Matic's existing
absorbed-iron/zinc sufficiency calculations.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import CompoundObservation
from .source_licence_policy import load_compound_observations

POLICY_VERSION = "phytate-selection-v1"

COMPOUND = "phytate"

# value_qualifier values that carry a real number (see
# CompoundObservation.value_qualifier's column comment, Prompt 5) —
# every other qualifier (below_detection_limit, below_quantification_limit,
# trace, not_reported, unparseable) has no usable value for this service.
MEASURED_QUALIFIERS = frozenset({"measured", "reported_zero"})

_PHYTIC_ACID_TAGS = frozenset({"PHYTCPPI", "PHYTCPPD", "PHYTCPP", "PHYTCA", "PHYTC-", "PHYT-"})
_PHYTATE_PHOSPHORUS_TAGS = frozenset({"PPI", "PPD", "PP-"})
_INDIVIDUAL_INOSITOL_TAGS = frozenset({"IP3", "IP4", "IP5", "IP6"})
# Broadest first — a food with IPSUM present makes every narrower
# inositol-phosphate tag in SUBSUMES[IPSUM] redundant; checked in this
# order so the *broadest available* summed tag is what other rows are
# reported as subsumed by, not an arbitrary one.
_SUMMED_INOSITOL_TAGS_PRIORITY = ("IPSUM", "IP4_A_IP5_A_IP6", "IP5_A_IP6")

FRACTION_FAMILY: dict[str, str] = {}
for _tag in _PHYTIC_ACID_TAGS:
    FRACTION_FAMILY[_tag] = "phytic_acid"
for _tag in _PHYTATE_PHOSPHORUS_TAGS:
    FRACTION_FAMILY[_tag] = "phytate_phosphorus"
for _tag in _INDIVIDUAL_INOSITOL_TAGS:
    FRACTION_FAMILY[_tag] = "inositol_phosphate"
for _tag in _SUMMED_INOSITOL_TAGS_PRIORITY:
    FRACTION_FAMILY[_tag] = "inositol_phosphate"

# Which narrower inositol-phosphate tags a given broad (summed) tag
# already includes — the "never sum overlapping individual and
# already-summed fractions" rule, expressed as data rather than ad hoc
# arithmetic.
SUBSUMES: dict[str, frozenset[str]] = {
    "IPSUM": frozenset({"IP3", "IP4", "IP5", "IP6", "IP5_A_IP6", "IP4_A_IP5_A_IP6"}),
    "IP4_A_IP5_A_IP6": frozenset({"IP4", "IP5", "IP6", "IP5_A_IP6"}),
    "IP5_A_IP6": frozenset({"IP5", "IP6"}),
}


@dataclass(frozen=True)
class SelectedObservation:
    compound_fraction: str
    family: str
    value: float
    unit: str
    basis: str
    value_qualifier: str
    source_dataset_name: str
    source_dataset_citation: str
    analytical_method: str | None
    match_relationship: str
    match_confidence: float | None
    preparation_compatible: bool | None
    explanation: str


@dataclass(frozen=True)
class DeclinedObservation:
    compound_fraction: str
    reason: str


@dataclass(frozen=True)
class SelectionResult:
    status: str  # no_data | insufficient_data | selected
    food_id: int
    compound: str
    selected: list[SelectedObservation]
    declined: list[DeclinedObservation]
    coverage: str
    explanation: str
    policy_version: str


def _preparation_compatible(source_preparation_state: str | None, preparation_context: str | None) -> bool | None:
    """None (unknown) whenever either side doesn't state a preparation —
    never guessed. A simple case-insensitive substring check, same
    convention as ingest_phytate.classify_match's prep_aligned check."""
    if not preparation_context or not source_preparation_state:
        return None
    return preparation_context.strip().lower() in source_preparation_state.lower()


def _to_selected_observation(row: CompoundObservation, preparation_context: str | None) -> SelectedObservation:
    family = FRACTION_FAMILY.get(row.compound_fraction, "other")
    return SelectedObservation(
        compound_fraction=row.compound_fraction or "unspecified",
        family=family,
        value=row.original_value,
        unit=row.original_unit,
        basis=row.original_basis,
        value_qualifier=row.value_qualifier,
        source_dataset_name=row.source_dataset_name,
        source_dataset_citation=row.source_dataset_citation,
        analytical_method=row.analytical_method,
        match_relationship=row.match_relationship,
        match_confidence=row.match_confidence,
        preparation_compatible=_preparation_compatible(row.source_preparation_state, preparation_context),
        explanation=(
            f"{family} family, analytical_method={row.analytical_method or 'unspecified'}, "
            f"reviewed match scope={row.match_relationship}"
            + (f" (confidence {row.match_confidence:.2f})" if row.match_confidence is not None else "")
        ),
    )


def select_phytate_observations(
    db: Session, food_id: int, surface: str, *, preparation_context: str | None = None,
) -> SelectionResult:
    """The one entry point for "what phytate data is usable for this
    food." Raises SourceLicenceError (via load_compound_observations) if
    `surface` isn't permitted — callers must let that propagate, same
    contract as the boundary function itself."""
    rows = (
        load_compound_observations(db, COMPOUND, surface)
        .filter(CompoundObservation.matched_food_id == food_id)
        .all()
    )

    if not rows:
        return SelectionResult(
            status="no_data", food_id=food_id, compound=COMPOUND, selected=[], declined=[],
            coverage="none", explanation="no phytate observations matched to this food",
            policy_version=POLICY_VERSION,
        )

    declined: list[DeclinedObservation] = []
    numeric_rows: list[CompoundObservation] = []
    for row in rows:
        if row.value_qualifier in MEASURED_QUALIFIERS:
            numeric_rows.append(row)
        else:
            declined.append(DeclinedObservation(
                compound_fraction=row.compound_fraction or "unspecified",
                reason=f"censored: value_qualifier={row.value_qualifier} (original text {row.original_value_text!r})",
            ))

    if not numeric_rows:
        declined.sort(key=lambda d: d.compound_fraction)
        return SelectionResult(
            status="insufficient_data", food_id=food_id, compound=COMPOUND, selected=[], declined=declined,
            coverage="censored_only",
            explanation=f"{len(declined)} observation(s) exist but all are censored/non-numeric — no usable value",
            policy_version=POLICY_VERSION,
        )

    inositol_rows = [r for r in numeric_rows if FRACTION_FAMILY.get(r.compound_fraction) == "inositol_phosphate"]
    other_rows = [r for r in numeric_rows if FRACTION_FAMILY.get(r.compound_fraction) != "inositol_phosphate"]

    # Subsumption only makes sense *within* one source measurement --
    # a broad summed tag from one source entry says nothing about
    # whether a narrower tag from a *different* source entry (a
    # different analysis, possibly a different lab/sample) is already
    # included in it. Grouping by the source_row_identifier prefix
    # before its ":TAGNAME" suffix (see app.phyfoodcomp_adapter, which
    # builds row_identifier as f"{row_identifier}:{tagname}") keeps two
    # independent source entries mapped to the same Food from
    # suppressing each other's fractions.
    inositol_by_source_entry: dict[str | None, list[CompoundObservation]] = {}
    for r in inositol_rows:
        key = r.source_row_identifier.split(":", 1)[0] if r.source_row_identifier else None
        inositol_by_source_entry.setdefault(key, []).append(r)

    kept_inositol: list[CompoundObservation] = []
    for group_rows in inositol_by_source_entry.values():
        present_tags = {r.compound_fraction for r in group_rows}
        subsumed_by: dict[str, str] = {}
        for broad_tag in _SUMMED_INOSITOL_TAGS_PRIORITY:
            if broad_tag not in present_tags:
                continue
            for narrower in SUBSUMES[broad_tag] & present_tags:
                subsumed_by.setdefault(narrower, broad_tag)

        for r in group_rows:
            if r.compound_fraction in subsumed_by:
                broad = subsumed_by[r.compound_fraction]
                declined.append(DeclinedObservation(
                    compound_fraction=r.compound_fraction,
                    reason=f"subsumed by {broad}, already present for this same source measurement and "
                           "inclusive of this fraction — summing them would double-count",
                ))
            else:
                kept_inositol.append(r)

    selected_rows = sorted(other_rows + kept_inositol, key=lambda r: (r.compound_fraction or "", r.id))
    declined.sort(key=lambda d: d.compound_fraction)

    selected = [_to_selected_observation(r, preparation_context) for r in selected_rows]
    families_present = sorted({FRACTION_FAMILY.get(r.compound_fraction, "other") for r in selected_rows})

    explanation_parts = [
        f"{len(selected)} observation(s) selected across {len(families_present)} family/families "
        f"({', '.join(families_present)})"
    ]
    if len(families_present) > 1:
        explanation_parts.append(
            "these measure different quantities (phytic acid vs. phytate-phosphorus vs. inositol phosphates) "
            "and are not directly comparable, summable, or averageable without a documented conversion"
        )
    if declined:
        explanation_parts.append(f"{len(declined)} observation(s) declined — see 'declined'")

    return SelectionResult(
        status="selected", food_id=food_id, compound=COMPOUND, selected=selected, declined=declined,
        coverage=", ".join(families_present), explanation="; ".join(explanation_parts),
        policy_version=POLICY_VERSION,
    )
