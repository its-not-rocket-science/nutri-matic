"""Matches a parsed ingredient to a Food row, in the priority order prompt
section 6 specifies:

    1. exact curated aliases       (ingredient_aliases.ALIASES)
    2. canonical ingredient mapping (deterministic Food.name prefix match)
    3. deterministic normalised-name matching (same tier as #2 here — see
       module docstring below for why they're merged)
    4. existing fuzzy-search service (search.search_foods_by_name)
    5. explicitly reviewed fallback mappings (ingredient_aliases.REVIEWED_FALLBACKS)

No LLM involvement anywhere in this file, per prompt section 6 — every
match is either a curated lookup or the app's existing deterministic/
trigram-backed search service, so every match is explainable and
reproducible from the stored match_method alone.

Tiers 2 and 3 are implemented as one step here: prompt section 6 describes
them as "canonical ingredient mappings" and "deterministic normalised-name
matching" separately, but the only deterministic (non-fuzzy) matching this
app has beyond the alias table *is* a normalised-name lookup against
Food.name — there's no separate "canonical mapping" data source to
consult first. Keeping them as one tier avoids inventing a distinction
that doesn't correspond to two different real behaviours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import case
from sqlalchemy.orm import Session

from ..dietary_tags import match_confidence as _data_type_confidence
from ..models import Food
from ..reference_patterns import AMINO_ACIDS
from ..search import search_foods_by_name
from .ingredient_aliases import ALIASES, REVIEWED_FALLBACKS, AliasTarget

# leading noise words stripped from a parsed ingredient name before
# matching — container/pack words the parser leaves in place (see
# ingredient_parser.py's docstring: it's honest about raw structure, not
# responsible for search normalisation) and quantity-adjacent leftovers.
_LEADING_STOPWORDS = (
    "tin", "tins", "can", "cans", "packet", "packets", "jar", "jars",
    "block", "blocks", "bag", "bags", "bottle", "bottles",
)
_LEADING_STOPWORD_RE = re.compile(
    r"^(?:" + "|".join(_LEADING_STOPWORDS) + r")\s+(?:of\s+)?", re.IGNORECASE,
)

_FUZZY_CONFIDENCE = {"high": 0.65, "low": 0.4}
_CANONICAL_CONFIDENCE = 0.85

# ALIASES/REVIEWED_FALLBACKS keys, longest first, each compiled as a
# whole-word pattern — built once at import time. A key matches if it
# appears anywhere in the normalised name as whole words, not just on an
# exact full-string match, so e.g. the "5% lean beef mince" ->
# "lean beef mince" suffix still resolves via the "lean beef mince" alias.
def _compile_lookup(table: dict[str, AliasTarget]) -> list[tuple[re.Pattern, str]]:
    return [
        (re.compile(rf"(?:^|\s){re.escape(key)}(?:$|\s)"), key)
        for key in sorted(table, key=len, reverse=True)
    ]


_ALIAS_PATTERNS = _compile_lookup(ALIASES)
_FALLBACK_PATTERNS = _compile_lookup(REVIEWED_FALLBACKS)


def _find_in_table(normalised: str, table: dict[str, AliasTarget], patterns: list[tuple[re.Pattern, str]]) -> AliasTarget | None:
    if normalised in table:
        return table[normalised]
    for pattern, key in patterns:
        if pattern.search(normalised):
            return table[key]
    return None


def normalise_ingredient_name(name: str) -> str:
    """Lowercased, leading container words stripped, whitespace collapsed —
    NOT a full normal form (no stemming/synonym work; search_foods_by_name
    already does that for the fuzzy tier). Used as the ALIASES/
    REVIEWED_FALLBACKS lookup key and as the deterministic-match query."""
    text = name.strip().lower()
    text = _LEADING_STOPWORD_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


@dataclass
class MatchCandidate:
    food_id: int
    name: str
    score: float


@dataclass
class MatchResult:
    food: Food | None
    method: str | None  # "alias" | "canonical" | "fuzzy" | "manual_review" | None (unresolved)
    confidence: float | None
    candidates: list[MatchCandidate] = field(default_factory=list)
    # the AliasTarget.relationship value ("exact" | "regional_equivalent" |
    # "close_analogue" | "category_proxy" | "reviewed_substitution") behind
    # an "alias"/"manual_review" method match — see ingredient_aliases.py.
    # None for "canonical"/"fuzzy" matches, which aren't alias-table driven.
    relationship: str | None = None

    @property
    def unresolved(self) -> bool:
        return self.food is None


def _candidates_from(foods: list[Food]) -> list[MatchCandidate]:
    return [
        MatchCandidate(food_id=f.id, name=f.name, score=round(1.0 - i * 0.08, 3))
        for i, f in enumerate(foods[:5])
    ]


def _lacks_amino_acids(food: Food) -> bool:
    """True if this food's amino acid panel is incomplete. Used as a
    matching tiebreaker: the same food commonly exists twice in FDC (once
    from Foundation Foods, once from SR Legacy — e.g. "Garlic, raw" —
    with only one of the two actually carrying amino acid data), and
    without this, ranking-by-name-alone picks whichever happens to sort
    first, silently blocking DIAAS/PDCAAS for every recipe that lands on
    the incomplete one even though the complete duplicate is sitting
    right there in the same database (found affecting ~180 recipes
    across just three ingredients: garlic, celery, crushed tomatoes)."""
    return any(food.amino_acids.get(aa) is None for aa in AMINO_ACIDS)


def _word_and_search(db: Session, phrase: str, limit: int = 5) -> list[Food]:
    """Every word in `phrase` must appear somewhere in Food.name — used for
    ALIASES/REVIEWED_FALLBACKS' curated multi-word search phrases, which
    are written as plain space-separated words ("beef ground") but the
    matching USDA-style name is comma-punctuated ("Beef, ground, 85% lean
    meat..."). A single-substring ILIKE (what search_foods_by_name does,
    correctly, for a free-text user query) would never match that; ANDing
    each word's own ILIKE does. Non-branded foods are preferred, same
    reasoning as search.py's own branded_last ordering.

    Ranking beyond that is NOT plain alphabetical — that let "olive oil"
    match "Mayonnaise, reduced fat, with olive oil" ahead of the actual
    "Oil, olive" entry purely because "Mayonnaise" sorts before "Oil"
    (found affecting 86 imported recipes). USDA-style names put the true
    category first ("Oil, olive..."), so a candidate whose *first*
    comma-segment is itself one of the query words is almost always the
    right generic match; a query word merely appearing later in the name
    (like "...with olive oil") is a much weaker signal."""
    words = [w for w in phrase.strip().split() if w]
    if not words:
        return []
    query = db.query(Food)
    for word in words:
        query = query.filter(Food.name.ilike(f"%{word}%"))
    branded_last = case((Food.data_type == "branded_food", 1), else_=0)
    # fetch a wider pool than `limit` so the Python-side re-rank below has
    # something to work with beyond whatever the DB's default tiebreak picked
    candidates = query.order_by(branded_last, Food.name).limit(max(limit * 8, 40)).all()

    word_set = {w.lower() for w in words}

    def rank(food: Food) -> tuple:
        first_segment = food.name.split(",")[0].strip().lower()
        # "starts with a query word" rather than "equals a query word" —
        # otherwise "Tomato products, canned, paste..." (first segment
        # "tomato products") loses this tiebreak to "Tomato, paste..."
        # (first segment "tomato") purely because "tomato products" != any
        # single query word, even though "tomato products" obviously still
        # starts with "tomato". Found starving out a complete-amino-acid
        # duplicate of tomato paste in favour of an incomplete one.
        first_segment_matches = not any(
            first_segment == w or first_segment.startswith(w + " ") for w in word_set
        )  # False (0) sorts first
        return (
            food.data_type == "branded_food", first_segment_matches, _lacks_amino_acids(food),
            len(food.name), food.name,
        )

    return sorted(candidates, key=rank)[:limit]


def _canonical_lookup(db: Session, normalised: str) -> Food | None:
    """A deterministic (non-fuzzy) Food.name match: the normalised
    ingredient name as either the whole name or the first comma-separated
    segment of a USDA-style name ("onions raw" -> "Onions, raw..."). Prefers
    Foundation/SR Legacy over branded, then a complete amino acid profile
    over an incomplete one (see _lacks_amino_acids), then the shortest
    (most generic) matching name."""
    candidates = (
        db.query(Food)
        .filter(Food.name.ilike(f"{normalised}%") | Food.name.ilike(f"{normalised},%"))
        .all()
    )
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f.data_type == "branded_food", _lacks_amino_acids(f), len(f.name)))
    return candidates[0]


def match_ingredient(db: Session, name: str) -> MatchResult:
    normalised = normalise_ingredient_name(name)
    if not normalised:
        return MatchResult(food=None, method=None, confidence=None)

    fuzzy_matches = search_foods_by_name(db, normalised, limit=5)
    candidates = _candidates_from(fuzzy_matches)

    alias_target = _find_in_table(normalised, ALIASES, _ALIAS_PATTERNS)
    if alias_target:
        alias_matches = _word_and_search(db, alias_target.search_phrase)
        if alias_matches:
            return MatchResult(
                alias_matches[0], "alias", alias_target.confidence, _candidates_from(alias_matches),
                relationship=alias_target.relationship.value,
            )

    canonical = _canonical_lookup(db, normalised)
    if canonical is not None:
        return MatchResult(canonical, "canonical", _CANONICAL_CONFIDENCE, candidates or _candidates_from([canonical]))

    if fuzzy_matches:
        best = fuzzy_matches[0]
        confidence = _FUZZY_CONFIDENCE[_data_type_confidence(best.data_type)]
        return MatchResult(best, "fuzzy", confidence, candidates)

    fallback_target = _find_in_table(normalised, REVIEWED_FALLBACKS, _FALLBACK_PATTERNS)
    if fallback_target:
        fallback_matches = _word_and_search(db, fallback_target.search_phrase)
        if fallback_matches:
            return MatchResult(
                fallback_matches[0], "manual_review", fallback_target.confidence, _candidates_from(fallback_matches),
                relationship=fallback_target.relationship.value,
            )

    return MatchResult(food=None, method=None, confidence=None, candidates=candidates)


@dataclass
class CoverageResult:
    line_coverage: float  # proportion of ingredient lines resolved (0-1)
    mass_coverage: float  # proportion of total known mass resolved (0-1)


def compute_coverage(resolutions: list[tuple[bool, float | None]]) -> CoverageResult:
    """`resolutions` is one (is_resolved, grams_or_none) pair per ingredient
    line — grams is None for an optional/unspecified-quantity line, which is
    excluded from the mass-coverage denominator entirely (it contributes no
    mass either way, so it shouldn't dilute or inflate the ratio).

    Mass coverage defaults to 1.0 when no line has a known mass at all
    (nothing to weight by — line coverage is the only meaningful signal in
    that case, so mass coverage shouldn't artificially drag a recipe down)."""
    if not resolutions:
        return CoverageResult(0.0, 0.0)

    line_coverage = sum(1 for resolved, _ in resolutions if resolved) / len(resolutions)

    total_mass = sum(g for _, g in resolutions if g is not None)
    if total_mass <= 0:
        return CoverageResult(line_coverage, 1.0)
    resolved_mass = sum(g for resolved, g in resolutions if resolved and g is not None)
    return CoverageResult(line_coverage, resolved_mass / total_mass)
