from fastapi import APIRouter

from .. import schemas
from ..nutrients import NUTRIENTS
from ..search import FOOD_FILTER_KEYS, RECIPE_FILTER_KEYS

router = APIRouter(prefix="/api/search", tags=["search"])

_SCORE_LABELS = {"diaas_score": ("DIAAS score", "%"), "pdcaas_score": ("PDCAAS score", "%")}
_SPECIAL_LABELS = {"protein_g_per_100g": ("Protein", "g")}


def _key_out(key: str) -> schemas.FilterKeyOut:
    if key in _SCORE_LABELS:
        label, unit = _SCORE_LABELS[key]
    elif key in _SPECIAL_LABELS:
        label, unit = _SPECIAL_LABELS[key]
    else:
        label, unit = NUTRIENTS[key].name, NUTRIENTS[key].unit
    return schemas.FilterKeyOut(key=key, label=label, unit=unit)


@router.get("/keys", response_model=dict[str, list[schemas.FilterKeyOut]])
def filter_keys():
    """Available filter keys for /api/foods/search and /api/recipes/search,
    with display labels/units — keeps the frontend from hand-maintaining a
    duplicate list of every nutrient."""
    return {
        "food": sorted((_key_out(k) for k in FOOD_FILTER_KEYS), key=lambda k: k.label),
        "recipe": sorted((_key_out(k) for k in RECIPE_FILTER_KEYS), key=lambda k: k.label),
    }
