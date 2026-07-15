from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..complement import suggest_complements
from ..database import get_db
from ..methodology import SCORING_METHODOLOGY_VERSION
from ..nutrients import NUTRIENTS, resolve_drv
from ..reference_patterns import DEFAULT_PATTERN
from ..scoring import IncompleteAminoAcidProfile, ScoreResult, UnknownReferencePattern, compute_diaas, compute_pdcaas
from ..search import NutrientFilter, UnknownFilterKey, search_foods, search_foods_by_name

router = APIRouter(prefix="/api/foods", tags=["foods"])

# human-readable label per Food.data_type, for the provenance endpoint —
# see ingest_fdc.py for how each is actually parsed/ingested
DATASET_LABELS = {
    "foundation_food": "USDA FoodData Central — Foundation Foods",
    "sr_legacy_food": "USDA FoodData Central — SR Legacy",
    "branded_food": "USDA FoodData Central — Branded Foods",
}


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


@router.get("", response_model=schemas.FoodListOut)
def list_foods(limit: int = 50, offset: int = 0, db: Session = Depends(get_db)):
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    base_query = db.query(models.Food)
    total = base_query.count()
    items = base_query.order_by(models.Food.name).offset(offset).limit(limit).all()
    return schemas.FoodListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.get("/search-by-name", response_model=list[schemas.FoodOut])
def food_search_by_name(q: str, limit: int = 20, db: Session = Depends(get_db)):
    """Name autocomplete for logging a diary/meal-plan entry or building a
    recipe — synonym/plural-aware substring matching, ranked by relevance,
    with typo-tolerant fuzzy fallback where the database supports it. See
    search.py's module docstring for the full design."""
    return search_foods_by_name(db, q, limit=limit)


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
        methodology_version=SCORING_METHODOLOGY_VERSION,
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
        methodology_version=SCORING_METHODOLOGY_VERSION,
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
        out.append(schemas.NutrientAmountOut.build(row.nutrient_key, nutrient_def, row.amount_per_100g, drv))
    out.sort(key=lambda n: n.name)
    return out


@router.get("/{food_id}/provenance", response_model=schemas.FoodProvenanceOut)
def food_provenance(food_id: int, db: Session = Depends(get_db)):
    """Full traceability chain for every value this food contributes:
    Food -> fdc_id/dataset -> USDA nutrient number -> FoodNutrient row ->
    DRV comparison. Raw amounts are always exactly as USDA reported them
    (this app never estimates/imputes a micronutrient amount — a food
    either has the row FDC gave it, or has no row for that nutrient at
    all), so the per-value provenance that actually varies is the DRV
    comparison side, not the amount itself."""
    food = db.get(models.Food, food_id)
    if food is None:
        raise HTTPException(status_code=404, detail="Food not found")

    rows = db.query(models.FoodNutrient).filter(models.FoodNutrient.food_id == food_id).all()
    nutrients_out = []
    for row in rows:
        nutrient_def = NUTRIENTS.get(row.nutrient_key)
        if nutrient_def is None:
            continue
        nutrients_out.append(
            schemas.NutrientProvenanceOut(
                key=row.nutrient_key,
                name=nutrient_def.name,
                fdc_nutrient_nbr=nutrient_def.fdc_nutrient_nbr,
                amount_per_100g=row.amount_per_100g,
                drv_source=nutrient_def.drv_source or None,
                drv_confidence=nutrient_def.drv_confidence if nutrient_def.drv_source else None,
            )
        )
    nutrients_out.sort(key=lambda n: n.name)

    return schemas.FoodProvenanceOut(
        food_id=food.id,
        food_name=food.name,
        fdc_id=food.fdc_id,
        data_type=food.data_type,
        dataset_label=DATASET_LABELS.get(food.data_type) if food.data_type else None,
        gtin_upc=food.gtin_upc,
        digestibility_diaas_source=food.digestibility_diaas_source,
        digestibility_pdcaas_source=food.digestibility_pdcaas_source,
        nutrients=nutrients_out,
    )
