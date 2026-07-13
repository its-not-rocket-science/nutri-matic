from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..micronutrients import NUTRIENTS
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas

router = APIRouter(prefix="/api/foods", tags=["foods"])


@router.post("", response_model=schemas.FoodOut, status_code=201)
def create_food(food: schemas.FoodCreate, db: Session = Depends(get_db)):
    db_food = models.Food(
        name=food.name,
        protein_g_per_100g=food.protein_g_per_100g,
        amino_acids=food.amino_acids.model_dump(),
        digestibility_diaas=food.digestibility_diaas.model_dump() if food.digestibility_diaas else None,
        digestibility_diaas_source=food.digestibility_diaas_source,
        digestibility_pdcaas=food.digestibility_pdcaas,
        digestibility_pdcaas_source=food.digestibility_pdcaas_source,
        fdc_id=food.fdc_id,
        data_type=food.data_type,
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
    except (UnknownReferencePattern, IncompleteAminoAcidProfile) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return schemas.ScoreOut(
        method=method,
        pattern_used=result.pattern_used,
        score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        per_aa_ratios=result.per_aa_ratios,
        digestibility_source=(
            food.digestibility_diaas_source if method == "diaas" else food.digestibility_pdcaas_source
        ),
    )


@router.get("/{food_id}/nutrients", response_model=list[schemas.NutrientAmountOut])
def food_nutrients(food_id: int, db: Session = Depends(get_db)):
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    rows = db.query(models.FoodNutrient).filter(models.FoodNutrient.food_id == food_id).all()
    out = []
    for row in rows:
        nutrient_def = NUTRIENTS.get(row.nutrient_key)
        if nutrient_def is None:
            continue
        drv = nutrient_def.adult_drv or None
        out.append(
            schemas.NutrientAmountOut(
                key=row.nutrient_key,
                name=nutrient_def.name,
                unit=nutrient_def.unit,
                amount_per_100g=row.amount_per_100g,
                adult_drv=drv,
                percent_drv_per_100g=(row.amount_per_100g / drv * 100) if drv else None,
            )
        )
    out.sort(key=lambda n: n.name)
    return out
