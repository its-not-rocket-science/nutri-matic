from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..complement import suggest_complements
from ..database import get_db
from ..nutrients import NUTRIENTS, resolve_drv
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import IncompleteAminoAcidProfile, ScoreResult, UnknownReferencePattern, compute_diaas, compute_pdcaas
from ..search import NutrientFilter, UnknownFilterKey, search_foods

router = APIRouter(prefix="/api/foods", tags=["foods"])


def _compute_score(food: models.Food, method: str, pattern: str) -> ScoreResult:
    """Shared by /score and /complement — raises HTTPException the same way
    both endpoints need to (missing digestibility data, unknown method,
    incomplete amino acid profile)."""
    try:
        if method == "diaas":
            if food.digestibility_diaas is None:
                raise HTTPException(
                    status_code=422, detail="Food has no per-amino-acid digestibility data for DIAAS"
                )
            return compute_diaas(food.amino_acids, food.digestibility_diaas, pattern)
        elif method == "pdcaas":
            if food.digestibility_pdcaas is None:
                raise HTTPException(
                    status_code=422, detail="Food has no overall digestibility data for PDCAAS"
                )
            return compute_pdcaas(food.amino_acids, food.digestibility_pdcaas, pattern)
        else:
            raise HTTPException(status_code=422, detail="method must be 'diaas' or 'pdcaas'")
    except (UnknownReferencePattern, IncompleteAminoAcidProfile) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


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
        gtin_upc=food.gtin_upc,
    )
    db.add(db_food)
    db.commit()
    db.refresh(db_food)
    return db_food


@router.get("", response_model=list[schemas.FoodOut])
def list_foods(db: Session = Depends(get_db)):
    return db.query(models.Food).order_by(models.Food.name).all()


@router.post("/search", response_model=list[schemas.FoodOut])
def food_search(body: schemas.SearchRequest, db: Session = Depends(get_db)):
    filters = [NutrientFilter(f.key, f.op, f.value) for f in body.filters]
    try:
        return search_foods(db, filters, limit=body.limit)
    except UnknownFilterKey as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/barcode/{gtin_upc}", response_model=schemas.FoodOut)
def get_food_by_barcode(gtin_upc: str, db: Session = Depends(get_db)):
    food = db.query(models.Food).filter(models.Food.gtin_upc == gtin_upc).one_or_none()
    if food is None:
        raise HTTPException(status_code=404, detail="No food found for that barcode")
    return food


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
    )


@router.get("/{food_id}/complement", response_model=schemas.ComplementOut)
def complement_food(
    food_id: int,
    method: str = "diaas",
    pattern: str = DEFAULT_PATTERN,
    db: Session = Depends(get_db),
):
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    result = _compute_score(food, method, pattern)
    suggestions = suggest_complements(food, result, method, pattern, db)

    return schemas.ComplementOut(
        original_score=result.score,
        limiting_amino_acid=result.limiting_amino_acid,
        suggestions=[
            schemas.ComplementSuggestionOut(
                food_id=s.food.id,
                food_name=s.food.name,
                combined_score=s.combined_score,
                score_improvement=s.score_improvement,
            )
            for s in suggestions
        ],
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
        # public/unauthenticated endpoint — always the generic adult_female
        # baseline; profile-aware DRVs are used by the diary/recipe endpoints
        drv = resolve_drv(row.nutrient_key, profile=None)
        out.append(
            schemas.NutrientAmountOut(
                key=row.nutrient_key,
                name=nutrient_def.name,
                unit=nutrient_def.unit,
                amount=row.amount_per_100g,
                adult_drv=drv,
                percent_drv=(row.amount_per_100g / drv * 100) if drv else None,
                drv_source=nutrient_def.drv_source or None,
            )
        )
    out.sort(key=lambda n: n.name)
    return out
