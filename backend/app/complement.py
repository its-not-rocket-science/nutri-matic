"""Protein complementation suggestions: given a food that's limited by one
amino acid, find other foods that would raise its DIAAS/PDCAAS score when
eaten alongside it — the classic "beans + rice" idea, computed rather than
hardcoded.

No new nutrition-science research here — this is pure composition of
machinery that already exists: aggregation.py's aggregate_amino_acids()
(protein-weighted combination, same math the recipe builder and diary use)
and scoring.py's compute_diaas/compute_pdcaas. A candidate is only ever
suggested if actually simulating the 100g-subject + 100g-candidate combo
produces a real, computed score improvement — never a guess based on raw
amino acid content alone.

Candidates are pre-filtered by raw amino acid content (cheap) before the
expensive simulation (aggregate + score) runs on the shortlist, since
running the full simulation against every food in the database would be
wasteful — a food weak in the limiting amino acid essentially never
improves the combined score, so this pre-filter doesn't change the result,
only the cost of getting there.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_amino_acids
from .dietary_filter import filter_excluded_foods
from .models import Food, Profile
from .scoring import IncompleteAminoAcidProfile, ScoreResult, compute_diaas, compute_pdcaas

SHORTLIST_SIZE = 30
PAIRING_QUANTITY_G = 100.0


@dataclass
class ComplementSuggestion:
    food: Food
    combined_score: float
    score_improvement: float


def _score(method: str, amino_acids: dict, digestibility, pattern: str) -> ScoreResult:
    if method == "diaas":
        return compute_diaas(amino_acids, digestibility, pattern)
    return compute_pdcaas(amino_acids, digestibility, pattern)


def suggest_complements(
    items: list[WeightedFood],
    original_score: ScoreResult,
    method: str,
    pattern: str,
    db: Session,
    limit: int = 5,
    profile: Profile | None = None,
) -> list[ComplementSuggestion]:
    """`items` is the subject's own weighted foods — a single 100g food
    (prompt 6's original single-food complement) or a recipe's own
    per-serving ingredient list (prompt 5.2, complementing a recipe as a
    whole rather than one ingredient in isolation); either way this never
    cares which. `original_score` is the caller's already-computed score
    for `items` — callers need it anyway (to show the user the current
    score), and recomputing it here would just be duplicate work. profile
    is optional (this is reachable signed-out for the single-food case) —
    when present, candidates with a hard dietary exclusion for that
    profile are dropped before ranking."""
    limiting_aa = original_score.limiting_amino_acid
    subject_food_ids = {item.food.id for item in items}

    digestibility_column = Food.digestibility_diaas if method == "diaas" else Food.digestibility_pdcaas
    candidates = db.query(Food).filter(~Food.id.in_(subject_food_ids), digestibility_column.isnot(None)).all()
    candidates = filter_excluded_foods(candidates, db, profile)

    ranked_by_raw_content = sorted(
        (c for c in candidates if c.amino_acids.get(limiting_aa) is not None),
        key=lambda c: c.amino_acids[limiting_aa],
        reverse=True,
    )
    shortlist = ranked_by_raw_content[:SHORTLIST_SIZE]

    results: list[ComplementSuggestion] = []
    for candidate in shortlist:
        combo = aggregate_amino_acids([*items, WeightedFood(candidate, PAIRING_QUANTITY_G)])
        if combo.total_protein_g <= 0:
            continue

        digestibility = combo.digestibility_diaas if method == "diaas" else combo.digestibility_pdcaas
        if digestibility is None:
            continue

        try:
            combined_score = _score(method, combo.amino_acids, digestibility, pattern)
        except IncompleteAminoAcidProfile:
            continue

        improvement = combined_score.score - original_score.score
        if improvement > 0:
            results.append(ComplementSuggestion(candidate, combined_score.score, improvement))

    results.sort(key=lambda r: r.score_improvement, reverse=True)
    return results[:limit]
