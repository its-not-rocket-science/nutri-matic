"""Versioned public API (Phase 3.2) — exposes the nutrition engine
(scoring, complementarity, bioavailability) to API-key-authenticated
external callers, separately from the JWT-session app routes everything
else in this file tree uses. Built on the same underlying functions those
routes call (scoring.py, complement.py, bioavailability.py) — not a
parallel reimplementation — so a fix or methodology change in one place
is never out of sync with the other.

Versioned as /api/v1 from the start (a URL prefix, not a header or content
negotiation scheme) so a future breaking v2 can be added alongside it
without disrupting existing integrations — the standard, simplest
approach for a public REST API.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..api_keys import get_api_key_user
from ..bioavailability import estimate_meal_iron_absorption, is_meat_fish_poultry, split_food_iron
from ..complement import suggest_complements
from ..database import get_db
from ..methodology import SCORING_METHODOLOGY_VERSION
from ..models import Food, FoodNutrient, User
from ..reference_patterns import DEFAULT_PATTERN
from .foods import _compute_score

router = APIRouter(prefix="/api/v1", tags=["public-api-v1"])


@router.get("/foods/{food_id}/score", response_model=schemas.ScoreOut)
def v1_score_food(
    food_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    current_user: User = Depends(get_api_key_user),
    db: Session = Depends(get_db),
):
    food = db.get(Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    result = _compute_score(food, method, pattern)
    return schemas.ScoreOut(
        method=method,
        pattern_used=result.pattern_used,
        score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        per_aa_ratios=result.per_aa_ratios,
        digestibility_source=(
            food.digestibility_diaas_source if method == "diaas" else food.digestibility_pdcaas_source
        ),
        methodology_version=SCORING_METHODOLOGY_VERSION,
    )


@router.get("/foods/{food_id}/complement", response_model=schemas.ComplementOut)
def v1_complement_food(
    food_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    current_user: User = Depends(get_api_key_user),
    db: Session = Depends(get_db),
):
    food = db.get(Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    result = _compute_score(food, method, pattern)
    suggestions = suggest_complements(food, result, method, pattern, db)

    return schemas.ComplementOut(
        original_score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        suggestions=[
            schemas.ComplementSuggestionOut(
                food_id=s.food.id, food_name=s.food.name, combined_score=s.combined_score,
                score_improvement=s.score_improvement,
            )
            for s in suggestions
        ],
        methodology_version=SCORING_METHODOLOGY_VERSION,
    )


@router.post("/bioavailability/iron", response_model=schemas.IronBioavailabilityResultOut)
def v1_iron_bioavailability(
    body: schemas.IronBioavailabilityRequest,
    current_user: User = Depends(get_api_key_user),
    db: Session = Depends(get_db),
):
    """Stateless counterpart to the diary's per-meal iron bioavailability —
    same real computation (bioavailability.py's Monsen-model constants),
    just against an arbitrary food+quantity list instead of a signed-in
    user's logged diary meal. Lets an external caller (e.g. a recipe app)
    compute a real absorption estimate for a meal they define, without
    needing a Nutri-Matic account or diary entries."""
    food_ids = {item.food_id for item in body.items}
    foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
    missing = food_ids - foods_by_id.keys()
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown food id(s): {sorted(missing)}")

    nutrient_rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all()
    by_food_id: dict[int, list[FoodNutrient]] = {}
    for row in nutrient_rows:
        by_food_id.setdefault(row.food_id, []).append(row)

    iron_splits = []
    vitamin_c_mg = 0.0
    has_mfp = False
    for item in body.items:
        food = foods_by_id[item.food_id]
        nutrients_by_key = {row.nutrient_key: row.amount_per_100g for row in by_food_id.get(item.food_id, [])}
        scale = item.quantity_g / 100
        total_iron_mg = nutrients_by_key.get("iron", 0.0) * scale
        measured_heme_mg = nutrients_by_key.get("iron_heme")
        measured_non_heme_mg = nutrients_by_key.get("iron_non_heme")
        if total_iron_mg > 0 or measured_heme_mg is not None or measured_non_heme_mg is not None:
            iron_splits.append(
                split_food_iron(
                    food.name,
                    total_iron_mg,
                    measured_heme_mg * scale if measured_heme_mg is not None else None,
                    measured_non_heme_mg * scale if measured_non_heme_mg is not None else None,
                )
            )
        vitamin_c_mg += nutrients_by_key.get("vitamin_c", 0.0) * scale
        if is_meat_fish_poultry(food.name):
            has_mfp = True

    estimate = estimate_meal_iron_absorption(iron_splits, vitamin_c_mg, has_mfp)
    if estimate is None:
        raise HTTPException(status_code=422, detail="None of the given foods carry any iron")

    return schemas.IronBioavailabilityResultOut(
        heme_iron_mg=estimate.heme_iron_mg,
        non_heme_iron_mg=estimate.non_heme_iron_mg,
        vitamin_c_mg=estimate.vitamin_c_mg,
        absorbed_heme_mg=estimate.absorbed_heme_mg,
        absorbed_non_heme_mg=estimate.absorbed_non_heme_mg,
        absorbed_total_mg=estimate.absorbed_total_mg,
        non_heme_absorption_tier=estimate.non_heme_absorption_tier,
        iron_split_source=estimate.iron_split_source,
    )
