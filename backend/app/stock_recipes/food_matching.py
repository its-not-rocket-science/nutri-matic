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

Text normalisation itself (lowercasing, stripping container words) lives
in linguistic_normalisation.py, not here — this module only decides what a
normalised name resolves to, never how it got normalised (prompt section
10: keep "make the text comparable" and "decide what food this means"
separable). `normalise_ingredient_name` is re-exported from here purely
for import-site convenience/backward compatibility.
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
from .linguistic_normalisation import normalise_ingredient_name

__all__ = [
    "normalise_ingredient_name",
    "MatchCandidate",
    "MatchResult",
    "CoverageResult",
    "match_ingredient",
    "compute_coverage",
    "validate_reviewed_mappings",
]

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
    # the AliasTarget.rationale behind an "alias"/"manual_review" match —
    # the human-readable sentence a user/developer should see (prompt
    # section 6). None for "canonical"/"fuzzy" matches.
    rationale: str | None = None
    # the AliasTarget's pinned fdc_id/food_id, if any was set, regardless
    # of whether it actually resolved (see `used_fallback`) — prompt
    # section 5's "preferred target identifier". Both None for a match
    # with no pinned id at all (an ordinary description-only alias).
    preferred_fdc_id: int | None = None
    preferred_food_id: int | None = None
    # True only when a preferred fdc_id/food_id WAS set but didn't resolve
    # to any Food row, so the description search_phrase resolved this
    # match instead — prompt section 5's "whether preferred-ID or fallback
    # search resolved the food". False when no fallback was needed
    # (either no id was pinned, or the pinned id resolved directly).
    used_fallback: bool = False
    # a human-readable note when something about this match's target
    # validation is worth a maintainer's attention — e.g. the pinned id
    # didn't resolve, or resolved to a food whose name has drifted from
    # what was recorded at review time. None when nothing is amiss.
    validation_warning: str | None = None

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


@dataclass
class AliasResolution:
    foods: list[Food]
    used_fallback: bool
    validation_warning: str | None = None


def _name_drift_warning(target: AliasTarget, food: Food) -> str | None:
    if target.expected_food_name is not None and food.name != target.expected_food_name:
        return (
            f"resolved food name {food.name!r} differs from expected {target.expected_food_name!r} "
            "recorded at review time — re-review recommended"
        )
    return None


def _resolve_alias_target(db: Session, target: AliasTarget) -> AliasResolution:
    """Prefer a stable `fdc_id`/`food_id` over the free-text
    `search_phrase` — the description-based word-and-search is a fallback
    only, used when neither id is pinned, or when a pinned id no longer
    resolves to any Food row at all (the referenced food was deleted or
    re-ingested under a new id). `fdc_id` is tried before `food_id` since
    it's the more portable identifier (see AliasTarget's docstring). See
    validate_reviewed_mappings for the startup/pipeline-time diagnostic
    that surfaces a dangling id instead of letting it silently degrade
    into whatever the fallback search happens to find."""
    if target.fdc_id is not None:
        food = db.query(Food).filter(Food.fdc_id == target.fdc_id).one_or_none()
        if food is not None:
            return AliasResolution([food], used_fallback=False, validation_warning=_name_drift_warning(target, food))

    if target.food_id is not None:
        food = db.get(Food, target.food_id)
        if food is not None:
            return AliasResolution([food], used_fallback=False, validation_warning=_name_drift_warning(target, food))

    foods = _word_and_search(db, target.search_phrase)
    had_preferred_target = target.fdc_id is not None or target.food_id is not None
    warning = (
        "preferred target id did not resolve to any Food row — resolved via fallback description search instead"
        if had_preferred_target else None
    )
    return AliasResolution(foods, used_fallback=had_preferred_target, validation_warning=warning)


def _lacks_nutrition_coverage(food: Food) -> str | None:
    """A one-line reason this preferred target can't fully back a
    protein-quality (DIAAS/PDCAAS) score, or None if its coverage is fine.
    Zero-protein foods (pure fats/oils/spices) are exempt — aggregation.py
    already excludes them from amino acid aggregation entirely, so an
    incomplete/absent amino acid profile there is expected, not a gap."""
    if food.protein_g_per_100g <= 0:
        return None
    if _lacks_amino_acids(food):
        return "incomplete amino acid profile"
    if food.digestibility_diaas is None and food.digestibility_pdcaas is None:
        return "no digestibility coefficient (DIAAS or PDCAAS) at all"
    return None


def validate_reviewed_mappings(db: Session) -> list[str]:
    """Checks every ALIASES/REVIEWED_FALLBACKS entry that pins a stable
    `fdc_id`/`food_id`, and returns one human-readable diagnostic string
    per problem found:

    * the id no longer resolves to any Food row at all (deleted, or the
      database was re-ingested and it now has a different id) — the
      entry will silently fall back to its description search until
      fixed, which may resolve to a different food entirely
    * the id still resolves, but Food.name has drifted from
      `expected_food_name` (the name a maintainer saw at review time) —
      not necessarily wrong, but worth a second look
    * the id resolves to a food with incomplete nutrition coverage for a
      protein-contributing ingredient (missing amino acids or
      digestibility) — the substitution itself may be sound, but it can
      never fully back a DIAAS/PDCAAS score as-is

    Read-only: never modifies the alias tables or the database. Intended
    to run at pipeline startup (see cli.py's `match` stage, and the
    standalone `validate-aliases` CLI command) so drift is caught
    immediately rather than surfacing later as an unexplained
    match-quality regression."""
    diagnostics: list[str] = []
    for table in (ALIASES, REVIEWED_FALLBACKS):
        for key, target in table.items():
            if target.fdc_id is None and target.food_id is None:
                continue

            food = None
            if target.fdc_id is not None:
                food = db.query(Food).filter(Food.fdc_id == target.fdc_id).one_or_none()
            if food is None and target.food_id is not None:
                food = db.get(Food, target.food_id)

            if food is None:
                pinned = f"fdc_id={target.fdc_id}" if target.fdc_id is not None else f"food_id={target.food_id}"
                diagnostics.append(
                    f"reviewed mapping {key!r} pins {pinned} (expected {target.expected_food_name!r}), "
                    f"which no longer exists in the database — falling back to description search "
                    f"{target.search_phrase!r}"
                )
                continue

            if target.expected_food_name is not None and food.name != target.expected_food_name:
                diagnostics.append(
                    f"reviewed mapping {key!r}'s preferred target name changed from "
                    f"{target.expected_food_name!r} to {food.name!r} — re-review recommended"
                )

            coverage_gap = _lacks_nutrition_coverage(food)
            if coverage_gap is not None:
                diagnostics.append(
                    f"reviewed mapping {key!r}'s preferred target {food.name!r} has {coverage_gap} — "
                    "can't fully back a protein-quality score"
                )
    return diagnostics


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
        resolution = _resolve_alias_target(db, alias_target)
        if resolution.foods:
            return MatchResult(
                resolution.foods[0], "alias", alias_target.confidence, _candidates_from(resolution.foods),
                relationship=alias_target.relationship.value, rationale=alias_target.rationale,
                preferred_fdc_id=alias_target.fdc_id, preferred_food_id=alias_target.food_id,
                used_fallback=resolution.used_fallback, validation_warning=resolution.validation_warning,
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
        resolution = _resolve_alias_target(db, fallback_target)
        if resolution.foods:
            return MatchResult(
                resolution.foods[0], "manual_review", fallback_target.confidence, _candidates_from(resolution.foods),
                relationship=fallback_target.relationship.value, rationale=fallback_target.rationale,
                preferred_fdc_id=fallback_target.fdc_id, preferred_food_id=fallback_target.food_id,
                used_fallback=resolution.used_fallback, validation_warning=resolution.validation_warning,
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
