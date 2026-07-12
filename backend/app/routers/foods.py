from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import UnknownReferencePattern, compute_diaas, compute_pdcaas

router = APIRouter(prefix="/api/foods", tags=["foods"])


@router.post("", response_model=schemas.FoodOut, status_code=201)
def create_food(food: schemas.FoodCreate, db: Session = Depends(get_db)):
    db_food = models.Food(
        name=food.name,
        protein_g_per_100g=food.protein_g_per_100g,
        amino_acids=food.amino_acids.model_dump(),
        digestibility_diaas=food.digestibility_diaas.model_dump() if food.digestibility_diaas else None,
        digestibility_pdcaas=food.digestibility_pdcaas,
    )
    db.add(db_food)
    db.commit()
    db.refresh(db_food)
    return db_food


@router.get("", response_model=list[schemas.FoodOut])
def list_foods(db: Session = Depends(get_db)):
    return db.query(models.Food).order_by(models.Food.name).all()


@router.get("/{food_id}", response_model=schemas.FoodOut)
def get_food(food_id: int, db: Session = Depends(get_db)):
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")
    return food


@router.get("/{food_id}/score", response_model=schemas.ScoreOut)
def score_food(
    food_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    db: Session = Depends(get_db),
):
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    try:
        if method == "diaas":
            if food.digestibility_diaas is None:
                raise HTTPException(
                    status_code=422, detail="Food has no per-amino-acid digestibility data for DIAAS"
                )
            result = compute_diaas(food.amino_acids, food.digestibility_diaas, pattern)
        elif method == "pdcaas":
            if food.digestibility_pdcaas is None:
                raise HTTPException(
                    status_code=422, detail="Food has no overall digestibility data for PDCAAS"
                )
            result = compute_pdcaas(food.amino_acids, food.digestibility_pdcaas, pattern)
        else:
            raise HTTPException(status_code=422, detail="method must be 'diaas' or 'pdcaas'")
    except UnknownReferencePattern as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return schemas.ScoreOut(
        method=method,
        pattern_used=result.pattern_used,
        score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        per_aa_ratios=result.per_aa_ratios,
    )
