"""Name search (this module) and nutrient-goal filtering (below) for foods
and recipes.

search_foods_by_name is deliberately built from SQLAlchemy operations that
compile identically on SQLite (what the test suite uses) and PostgreSQL
(production) — synonym expansion, singular/plural normalization, and
substring matching via .ilike(), plus Python-side (difflib, stdlib)
relevance ranking. Real fuzzy/typo-tolerant matching at full-catalog scale
needs something like PostgreSQL's pg_trgm extension, which SQLite has no
equivalent for; that layer is gated on the live session's actual dialect
(checked at query time, not assumed) so it activates automatically in
production without breaking the SQLite-based test suite.

Filters are ANDed together. A filter's key is either a nutrients.NUTRIENTS
key (compared against per-100g for a food, per-serving for a recipe),
"protein_g_per_100g" (foods only — a recipe has no single protein-per-100g
figure), or one of the two computed scores "diaas_score" / "pdcaas_score"
(using the child_3y_adult reference pattern, same default the rest of the
app uses). A food/recipe that can't be scored (missing digestibility data)
simply doesn't match a score filter, rather than raising — search isn't
the place to surprise a caller with a 422 for an unrelated food.

Filters are ANDed together. A filter's key is either a nutrients.NUTRIENTS
key (compared against per-100g for a food, per-serving for a recipe),
"protein_g_per_100g" (foods only — a recipe has no single protein-per-100g
figure), or one of the two computed scores "diaas_score" / "pdcaas_score"
(using the child_3y_adult reference pattern, same default the rest of the
app uses). A food/recipe that can't be scored (missing digestibility data)
simply doesn't match a score filter, rather than raising — search isn't
the place to surprise a caller with a 422 for an unrelated food.

Food search runs stored-nutrient filters as SQL (a subquery per nutrient
key, intersected via Food.id.in_()) so it scales to the full catalog;
score filters are evaluated in Python afterward since compute_diaas/
compute_pdcaas aren't SQL-expressible — fine because they only run against
whatever the SQL filters already narrowed down (or the whole catalog, in
the low-thousands, which is still cheap pure-Python arithmetic).

Recipe search skips the SQL step entirely and just evaluates every one of
the user's own recipes in Python — there are typically only a handful.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from .models import Food, FoodNutrient, Recipe, RecipeIngredient
from .nutrients import NUTRIENTS
from .reference_patterns import DEFAULT_PATTERN
from .scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas

Op = Literal["gte", "lte", "eq"]

SCORE_KEYS = {"diaas_score", "pdcaas_score"}
FOOD_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS | {"protein_g_per_100g"}
RECIPE_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS

# Common food-search synonyms/aliases — a modest, hand-picked list rather
# than a general thesaurus. Each key's search also matches foods named with
# any of its values; kept symmetric (both directions listed) so a search
# for either term finds foods named with the other.
FOOD_SYNONYMS: dict[str, list[str]] = {
    "egg": ["hen egg"],
    "hen egg": ["egg"],
    "chicken": ["hen", "poultry"],
    "hen": ["chicken"],
    "aubergine": ["eggplant"],
    "eggplant": ["aubergine"],
    "courgette": ["zucchini"],
    "zucchini": ["courgette"],
    "garbanzo": ["chickpea"],
    "chickpea": ["garbanzo"],
    "scallion": ["green onion", "spring onion"],
    "spring onion": ["scallion", "green onion"],
    "coriander": ["cilantro"],
    "cilantro": ["coriander"],
    "ground beef": ["beef mince"],
    "beef mince": ["ground beef"],
    "capsicum": ["bell pepper", "pepper"],
    "bell pepper": ["capsicum"],
    "shrimp": ["prawn"],
    "prawn": ["shrimp"],
    "yoghurt": ["yogurt"],
    "yogurt": ["yoghurt"],
    "soda": ["soft drink", "pop"],
}


def _singularize(word: str) -> str | None:
    """Cheap plural -> singular heuristic, not a full stemmer — strips a
    trailing 's' (but not 'ss', so "grass" doesn't become "gras"). Returns
    None if the word doesn't look pluralized."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return None


def expand_query_terms(query: str) -> list[str]:
    """The original query plus its plural/singular counterpart and any
    known synonyms — the full set of substrings actually searched for, so
    "eggs", "egg", and "hen egg" are all treated as the same search."""
    query = query.strip().lower()
    terms = {query}

    singular = _singularize(query)
    if singular:
        terms.add(singular)
    else:
        terms.add(query + "s")

    for term in list(terms):
        terms.update(FOOD_SYNONYMS.get(term, []))

    return sorted(terms)


def _rank_by_relevance(foods: list[Food], query: str, limit: int) -> list[Food]:
    """Portable relevance ranking (difflib, stdlib — no database-specific
    function needed): exact match first, then prefix matches, then by
    string similarity to the raw query."""
    query_lower = query.strip().lower()

    def sort_key(food: Food) -> tuple:
        name_lower = food.name.lower()
        is_exact = name_lower == query_lower
        is_prefix = name_lower.startswith(query_lower)
        similarity = SequenceMatcher(None, query_lower, name_lower).ratio()
        return (not is_exact, not is_prefix, -similarity)

    return sorted(foods, key=sort_key)[:limit]


def search_foods_by_name(db: Session, query: str, limit: int = 20) -> list[Food]:
    """Synonym/plural-aware substring search, ranked by relevance — the
    food-name autocomplete used when logging a diary/meal-plan entry or
    building a recipe. Falls back to PostgreSQL trigram similarity for
    typo tolerance when running against Postgres and the substring pass
    didn't fill the result list; see the module docstring for why that
    part is gated on the actual DB dialect."""
    query = query.strip()
    if len(query) < 2:
        return []

    terms = expand_query_terms(query)
    conditions = [Food.name.ilike(f"%{t}%") for t in terms]
    candidates = db.query(Food).filter(or_(*conditions)).order_by(Food.name).limit(limit * 5).all()
    ranked = _rank_by_relevance(candidates, query, limit)

    if len(ranked) >= limit or db.bind is None or db.bind.dialect.name != "postgresql":
        return ranked

    already_matched_ids = {f.id for f in ranked}
    fuzzy_rows = db.execute(
        text(
            "SELECT id FROM foods WHERE similarity(name, :q) > 0.2 "
            "ORDER BY similarity(name, :q) DESC LIMIT :fetch_limit"
        ),
        {"q": query, "fetch_limit": limit * 2},
    ).fetchall()
    fuzzy_ids = [row[0] for row in fuzzy_rows if row[0] not in already_matched_ids]
    if fuzzy_ids:
        fuzzy_foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(fuzzy_ids)).all()}
        ranked.extend(fuzzy_foods_by_id[i] for i in fuzzy_ids if i in fuzzy_foods_by_id)

    return ranked[:limit]


@dataclass
class NutrientFilter:
    key: str
    op: Op
    value: float


class UnknownFilterKey(ValueError):
    pass


def _compare(actual: float, op: Op, value: float) -> bool:
    if op == "gte":
        return actual >= value
    if op == "lte":
        return actual <= value
    return actual == value


def _score(amino_acids: dict, digestibility_diaas: dict | None, digestibility_pdcaas: float | None, score_key: str) -> float | None:
    try:
        if score_key == "diaas_score":
            if digestibility_diaas is None:
                return None
            return compute_diaas(amino_acids, digestibility_diaas, DEFAULT_PATTERN).score
        if score_key == "pdcaas_score":
            if digestibility_pdcaas is None:
                return None
            return compute_pdcaas(amino_acids, digestibility_pdcaas, DEFAULT_PATTERN).score
    except (IncompleteAminoAcidProfile, UnknownReferencePattern):
        return None
    return None


def search_foods(db: Session, filters: list[NutrientFilter], limit: int = 100) -> list[Food]:
    unknown = {f.key for f in filters} - FOOD_FILTER_KEYS
    if unknown:
        raise UnknownFilterKey(f"Unknown filter key(s): {sorted(unknown)}")

    query = db.query(Food)
    score_filters = []

    for f in filters:
        if f.key in SCORE_KEYS:
            score_filters.append(f)
        elif f.key == "protein_g_per_100g":
            query = query.filter(_op_clause(Food.protein_g_per_100g, f.op, f.value))
        else:
            subquery = db.query(FoodNutrient.food_id).filter(
                FoodNutrient.nutrient_key == f.key,
                _op_clause(FoodNutrient.amount_per_100g, f.op, f.value),
            )
            query = query.filter(Food.id.in_(subquery))

    candidates = query.order_by(Food.name).all()

    if not score_filters:
        return candidates[:limit]

    matches = [
        food
        for food in candidates
        if all(
            (score := _score(food.amino_acids, food.digestibility_diaas, food.digestibility_pdcaas, f.key))
            is not None
            and _compare(score, f.op, f.value)
            for f in score_filters
        )
    ]
    return matches[:limit]


def search_recipes(db: Session, user_id: int, filters: list[NutrientFilter]) -> list[Recipe]:
    unknown = {f.key for f in filters} - RECIPE_FILTER_KEYS
    if unknown:
        raise UnknownFilterKey(f"Unknown filter key(s): {sorted(unknown)}")

    recipes = db.query(Recipe).filter(Recipe.user_id == user_id).order_by(Recipe.name).all()
    matches = []

    for recipe in recipes:
        ingredients = db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == recipe.id).all()
        if not ingredients:
            continue
        food_ids = [i.food_id for i in ingredients]
        foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(food_ids)).all()}
        items = [WeightedFood(foods_by_id[i.food_id], i.quantity_g) for i in ingredients]

        nutrient_rows = db.query(FoodNutrient).filter(FoodNutrient.food_id.in_(food_ids)).all()
        by_food_id: dict[int, list[FoodNutrient]] = {}
        for row in nutrient_rows:
            by_food_id.setdefault(row.food_id, []).append(row)
        per_serving = aggregate_nutrients(items, by_food_id, divide_by=recipe.servings)
        aa_aggregate = aggregate_amino_acids(items)

        if _recipe_matches(per_serving, aa_aggregate, filters):
            matches.append(recipe)

    return matches


def _recipe_matches(per_serving: dict[str, float], aa_aggregate, filters: list[NutrientFilter]) -> bool:
    for f in filters:
        if f.key in SCORE_KEYS:
            score = _score(
                aa_aggregate.amino_acids, aa_aggregate.digestibility_diaas, aa_aggregate.digestibility_pdcaas, f.key
            )
            if score is None or not _compare(score, f.op, f.value):
                return False
        else:
            actual = per_serving.get(f.key)
            if actual is None or not _compare(actual, f.op, f.value):
                return False
    return True


def _op_clause(column, op: Op, value: float):
    if op == "gte":
        return column >= value
    if op == "lte":
        return column <= value
    return column == value
