"""PROMPT 7 of the phytate/mineral-bioavailability extension (see
prompts.txt) — the minimum internal API the ordinary personal UI needs
on top of app.phytate_selection. Public/unauthenticated, same as
foods.py's /score, /nutrients, and /provenance endpoints: this surface
must be available on identical terms to free and paid accounts, so it
never reads current_user or User.plan at all rather than relying on a
plan check that happens to return the same answer for everyone.

Enforces SURFACE_PERSONAL_FREE_INTERNAL_API through
app.source_licence_policy.require_surface — a prohibited-surface call is
structurally impossible here (this router only ever asks for that one
surface), but the dependency is still explicit so a future edit can't
quietly change which surface this endpoint claims to be.

Single food_id per request only, no bulk/list-all/export endpoint, and
MAX_OBSERVATIONS_RETURNED caps how many individual observations one
response can carry — prompts.txt PROMPT 7's requirement not to leak the
entire licensed source dataset or enable bulk reconstruction of it via
many small requests plus no natural per-food limit."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..phytate_selection import POLICY_VERSION, select_phytate_observations
from ..source_licence_policy import PHYFOODCOMP_1_0, SURFACE_PERSONAL_FREE_INTERNAL_API, require_surface

router = APIRouter(prefix="/api/foods", tags=["phytate"])

# NOT a low ceiling based on the 16 tagged fractions
# (phyfoodcomp_adapter._PHYTATE_TAGNAMES) -- a real food can have many
# independent source entries each reporting the same fraction (bot-review
# finding on PR #52's stack: real foods with 62/48/24 selected observations
# exist, from repeated measurements, not from 16+ distinct fraction types).
# 200 is comfortably above every real food observed while still refusing
# to serve something shaped like a bulk export of the whole licensed
# dataset from one food's response.
MAX_OBSERVATIONS_RETURNED = 200

# Only these match_relationship values reflect anything short of a
# source-verified identity match — see ingest_phytate.classify_match's
# own docstring on why "exact" is never assigned automatically today, so
# in practice this is every value currently in the table. Kept as an
# explicit set (rather than "not exact") so a future match_relationship
# addition must be deliberately classified here too.
_ESTIMATE_RELATIONSHIPS = frozenset({"regional_equivalent", "close_analogue", "category_proxy", "needs_review"})


@router.get("/{food_id}/phytate", response_model=schemas.PhytateOut)
def food_phytate(
    food_id: int,
    preparation: str | None = None,
    db: Session = Depends(get_db),
    _surface_ok=Depends(require_surface(source_key=PHYFOODCOMP_1_0, surface=SURFACE_PERSONAL_FREE_INTERNAL_API)),
):
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    result = select_phytate_observations(db, food_id, SURFACE_PERSONAL_FREE_INTERNAL_API, preparation_context=preparation)

    observations = result.selected[:MAX_OBSERVATIONS_RETURNED]
    truncated = len(result.selected) > MAX_OBSERVATIONS_RETURNED

    return schemas.PhytateOut(
        food_id=food_id,
        status=result.status,
        coverage=result.coverage,
        explanation=result.explanation,
        methodology_version=POLICY_VERSION,
        truncated=truncated,
        observations=[
            schemas.PhytateObservationOut(
                compound_fraction=o.compound_fraction,
                family=o.family,
                value=o.value,
                unit=o.unit,
                basis=o.basis,
                value_qualifier=o.value_qualifier,
                source_dataset_name=o.source_dataset_name,
                source_dataset_citation=o.source_dataset_citation,
                analytical_method=o.analytical_method,
                match_relationship=o.match_relationship,
                match_confidence=o.match_confidence,
                is_estimate=o.match_relationship in _ESTIMATE_RELATIONSHIPS,
                preparation_compatible=o.preparation_compatible,
                explanation=o.explanation,
            )
            for o in observations
        ],
    )
