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

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.orm import Session

from .aggregation import WeightedFood, aggregate_amino_acids, aggregate_nutrients
from .food_preparation import (
    NOT_STATED_LABEL,
    classify_preparation,
    preferred_preparation,
    preparation_label,
    preparation_rank,
)
from .models import CanonicalAlias, CanonicalFood, Food, FoodNutrient, Recipe, RecipeIngredient, RecipeShare
from .nutrients import NUTRIENTS
from .reference_patterns import DEFAULT_PATTERN
from .scoring import IncompleteAminoAcidProfile, UnknownReferencePattern, compute_diaas, compute_pdcaas
from .search_locale import EN_US, search_locale
from .search_synonyms import FOOD_SYNONYMS, phrase_synonyms, token_synonyms

Op = Literal["gte", "lte", "eq"]

SCORE_KEYS = {"diaas_score", "pdcaas_score"}
FOOD_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS | {"protein_g_per_100g"}
RECIPE_FILTER_KEYS = set(NUTRIENTS) | SCORE_KEYS


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


# --- food name search ---------------------------------------------------
#
# Ranking design: docs/plans/canonical-foods-plan.md sections 1.2 and 3.3
# (PR 1). In short:
#   * a query becomes one or more *variants* (the literal words, plus any
#     locale phrase synonyms); a food matches a variant when its name
#     contains every word of it, in any order (token-AND), each word being
#     allowed its plural/singular and token-synonym alternatives;
#   * generic (Foundation / SR Legacy / manual) rows rank before branded
#     ones in the final sort, not just in the candidate pool;
#   * similarity is measured against the term that actually matched, not
#     the raw query ("aubergine" ranks eggplant rows by "eggplant");
#   * preparation state is a tie-break (never a filter);
#   * branded rows are collapsed to one result per product name, keeping
#     the newest FDC version.
#
# Tier 1 (plan 3.3, PR 4b) comes before all of that: a query that is
# exactly a reviewed canonical alias (canonical_foods tables, loaded from
# app/canonical_foods/canonical_foods_en_gb.csv) returns that canonical's
# anchor row first, followed by the concept's other preparation variants.
# The ranked token search fills the rest of the list, without repeats.

_USDA_BOILERPLATE = "(includes foods for usda's food distribution program)"
_STOP_WORDS = frozenset({"and", "or", "with", "of", "the", "a", "&", "in"})
# Candidate pool sizes per rank group. Generic rows are few (~8k in total)
# so a generous pool is cheap; branded pools are larger because FDC
# publishes up to a dozen versions of one product and they collapse to one.
_GENERIC_POOL_MIN = 150
_BRANDED_POOL_FACTOR = 20


def _inflections(word: str) -> set[str]:
    """The word plus singular forms (substring matching makes the singular
    a superset of the plural, so plurals need no separate entry)."""
    forms = {word}
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        forms.add(word[:-1])
        if word.endswith("ies") and len(word) > 4:
            forms.add(word[:-3] + "y")
        if word.endswith("oes") and len(word) > 4:
            forms.add(word[:-2])
    if "-" in word:
        forms.add(word.replace("-", " "))
    return forms


@dataclass(frozen=True)
class QueryVariant:
    """One reading of the query. `words` holds, per required word, the
    alternatives any one of which satisfies it; `primary` the subset that
    is the word as typed (or its synonym), without plural stripping, so
    "tomatoes" ranks "Tomatoes, crushed" above "Tomato juice". Lower `rank`
    sorts first."""

    words: tuple[tuple[str, ...], ...]
    rank: int
    relationship: str | None = None  # None: the literal query
    note: str | None = None
    primary: tuple[frozenset[str], ...] = ()

    def all_primary(self, name_lower: str) -> bool:
        return all(any(p in name_lower for p in forms) for forms in self.primary)

    def match(self, name_lower: str) -> tuple[str, ...] | None:
        """The alternative that matched for each word, or None if the name
        does not contain every word. Prefers an alternative found at the
        start of a word ("swede" in "Swede, raw" over "Sweden")."""
        chosen = []
        for alternatives in self.words:
            present = [a for a in alternatives if a in name_lower]
            if not present:
                return None
            at_word_start = [a for a in present if _at_word_start(a, name_lower)]
            chosen.append((at_word_start or present)[0])
        return tuple(chosen)


def _at_word_start(term: str, name_lower: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term), name_lower) is not None


def _as_whole_word(term: str, name_lower: str) -> bool:
    """`term` as a whole word, allowing a plural ending: "apple" in
    "Apples, raw" but not in "APPLEBEE'S"."""
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?:e?s)?(?![a-z0-9])", name_lower) is not None


def _word_level(chosen: tuple[str, ...], name_lower: str) -> int:
    """0: every word whole; 1: every word at least starts a word; 2: some
    word only inside another ("oat" in "goat")."""
    if all(_as_whole_word(t, name_lower) for t in chosen):
        return 0
    if all(_at_word_start(t, name_lower) for t in chosen):
        return 1
    return 2


def _head_level(chosen: tuple[str, ...], name_lower: str) -> int:
    """How well the name's head noun (first comma segment, before any
    bracket) matches: 0 it *is* a matched word ("Beans, cannellini, dry"
    for "beans"), 1 it contains one ("Chili with beans"), 2 neither."""
    head = name_lower.split(",", 1)[0].split("(", 1)[0].strip()
    if any(re.fullmatch(re.escape(t) + r"(?:e?s)?", head) for t in chosen):
        return 0
    if any(_at_word_start(t, head) for t in chosen):
        return 1
    return 2


def _normalise_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def expand_food_query(query: str, locale: str) -> list[QueryVariant]:
    """The literal query (token-AND, with plural and token-synonym
    alternatives per word) plus the locale's phrase synonyms for the whole
    query. A `preferred` phrase synonym outranks the literal reading."""
    q = _normalise_query(query)
    words = [w for w in q.split() if w not in _STOP_WORDS] or q.split()

    def as_typed(word: str) -> set[str]:
        return {word, word.replace("-", " ")}

    def primary_forms(word: str, with_token_synonyms: bool) -> frozenset[str]:
        forms = as_typed(word)
        if with_token_synonyms:
            for f in _inflections(word):
                for synonym in token_synonyms(f, locale):
                    forms |= as_typed(synonym)
        return frozenset(forms)

    def alternatives(word: str, with_token_synonyms: bool) -> tuple[str, ...]:
        forms = set()
        for f in primary_forms(word, with_token_synonyms):
            forms |= _inflections(f)
        # longest first so the matched term shown/ranked is the fullest form
        return tuple(sorted(forms, key=lambda f: (-len(f), f)))

    synonyms = phrase_synonyms(q, locale)
    if not synonyms and len(words) >= 1:
        # "swedes" / "biscuits": try the phrase with its last word singular
        last_forms = _inflections(words[-1]) - {words[-1]}
        for form in sorted(last_forms):
            synonyms = phrase_synonyms(" ".join(q.split()[:-1] + [form]), locale)
            if synonyms:
                break

    any_preferred = any(s.preferred for s in synonyms)
    variants = [QueryVariant(
        tuple(alternatives(w, True) for w in words),
        rank=1 if any_preferred else 0,
        primary=tuple(primary_forms(w, True) for w in words),
    )]
    for synonym in synonyms:
        variants.append(QueryVariant(
            tuple(alternatives(w, False) for w in synonym.words),
            rank=0 if synonym.preferred or not any_preferred else 1,
            relationship=synonym.relationship,
            note=synonym.note,
            primary=tuple(primary_forms(w, False) for w in synonym.words),
        ))

    deduped: dict[tuple, QueryVariant] = {}
    for v in sorted(variants, key=lambda v: v.rank):
        deduped.setdefault(tuple(frozenset(a) for a in v.words), v)
    return list(deduped.values())


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _variant_condition(variant: QueryVariant):
    return and_(*[
        or_(*[Food.name.ilike(f"%{_escape_like(a)}%", escape="\\") for a in alternatives])
        for alternatives in variant.words
    ])


@dataclass
class FoodSearchHit:
    """A ranked search result plus what the UI needs to explain it."""

    food: Food
    preparation_state: str
    preparation_label: str | None
    matched_term: str
    relationship: str | None = None
    note: str | None = None
    # set on tier-1 results only: the reviewed canonical this row anchors,
    # its display name in the request locale, and where the logged row's
    # values come from ("USDA SR Legacy", plan 3.2)
    canonical_key: str | None = None
    canonical_name: str | None = None
    canonical_source: str | None = None


_CANONICAL_SOURCE = {"sr_legacy_food": "USDA SR Legacy", "foundation_food": "USDA Foundation"}


def _is_branded(food: Food) -> bool:
    return food.data_type == "branded_food"


def _rank_hits(foods: list[Food], variants: list[QueryVariant], query: str, locale: str) -> list[FoodSearchHit]:
    """Final sort, in key order:
      1. variant rank (a locale's preferred reading before the literal one)
      2. generic before branded
      3. every query word found as a whole word, else at a word start
         ("apple" in "Apples, raw" before "APPLEBEE'S"; "swede" not
         "Sweden"; "oat" not inside "goat")
      4. exact name match
      5. every word found as typed, not only via its singular: "tomatoes"
         ranks "Tomatoes, crushed, canned" above "Tomato juice, canned"
      6. the name's head noun (first comma segment) is, or else contains,
         a query word: "Beans, cannellini, dry" before "Chili with beans";
         "Milk, reduced fat, ..., 2% milkfat" before "Cheese, cottage, ...,
         2% milkfat"
      7. preparation tie-break (food_preparation.preparation_rank)
      8. name starts with the matched term
      9. similarity to the matched term, not the raw query
    When a food matches several readings, the best-ranked one counts.
    """
    q = _normalise_query(query)
    preferred_state = preferred_preparation(q, locale)
    keyed = []
    for food in foods:
        name_lower = food.name.lower()
        # punctuation-free form for the prefix test, so "cookies marie
        # biscuit" is a prefix of "Cookies, Marie biscuit"
        plain_name = " ".join(re.sub(r"[,()]", " ", name_lower).split())
        # similarity and length ignore FDC's distribution-programme
        # boilerplate, which otherwise makes the standard row look "longer"
        compare_name = name_lower.replace(_USDA_BOILERPLATE, "").strip()
        state = classify_preparation(food.name, food.data_type)
        prep_rank = preparation_rank(state, preferred_state)
        best = None
        for variant in variants:
            chosen = variant.match(name_lower)
            if chosen is None:
                continue
            matched_term = " ".join(chosen)
            sort_key = (
                variant.rank,
                _is_branded(food),
                _word_level(chosen, name_lower),
                not (name_lower == matched_term or name_lower == q),
                not variant.all_primary(name_lower),
                _head_level(chosen, name_lower),
                prep_rank,
                not plain_name.startswith(matched_term),
                -SequenceMatcher(None, matched_term, compare_name).ratio(),
                len(compare_name),
                name_lower,
            )
            if best is None or sort_key < best[0]:
                best = (sort_key, variant, matched_term)
        if best is None:
            continue
        sort_key, variant, matched_term = best
        label = preparation_label(state, locale)
        if label is None and preferred_state is not None and state != "unknown":
            label = NOT_STATED_LABEL
        hit = FoodSearchHit(food, state, label, matched_term, variant.relationship, variant.note)
        keyed.append((sort_key, hit))
    keyed.sort(key=lambda pair: pair[0])
    return [hit for _, hit in keyed]


def _collapse_branded_versions(hits: list[FoodSearchHit]) -> list[FoodSearchHit]:
    """One result per branded product. FDC publishes a new fdc_id for each
    label revision of the same product (plan 1.1.1); keep the newest
    (highest fdc_id) at the position of the best-ranked version."""
    best_by_name: dict[str, FoodSearchHit] = {}
    for hit in hits:
        if not _is_branded(hit.food):
            continue
        key = " ".join(hit.food.name.lower().split())
        current = best_by_name.get(key)
        if current is None or (hit.food.fdc_id or hit.food.id) > (current.food.fdc_id or current.food.id):
            best_by_name[key] = hit
    out, seen = [], set()
    for hit in hits:
        if not _is_branded(hit.food):
            out.append(hit)
            continue
        key = " ".join(hit.food.name.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(best_by_name[key])
    return out


def _rank_by_relevance(foods: list[Food], query: str, limit: int, locale: str | None = None) -> list[Food]:
    """Rank already-fetched foods for `query` (see _rank_hits). Foods that
    match no reading of the query are dropped."""
    locale = locale or search_locale()
    variants = expand_food_query(query, locale)
    return [h.food for h in _rank_hits(foods, variants, query, locale)][:limit]


def _alias_forms(q: str) -> set[str]:
    """The query and its last word's plural/singular forms, so "chickpea"
    finds the alias "chickpeas" and "swedes" finds "swede"."""
    words = q.split()
    head, last = words[:-1], words[-1]
    forms = {q} | {" ".join(head + [f]) for f in _inflections(last)}
    if not last.endswith("s"):
        forms |= {q + "s", q + "es"}
    return forms


def _canonical_hits(db: Session, query: str, locale: str) -> list[FoodSearchHit]:
    """Tier 1 (plan 3.3): canonicals with an alias equal to the query in the
    request locale or in any locale ('*'), plus the other active
    preparation variants of the same concepts as siblings.

    Order: concepts matched in the request locale before '*' ones, and
    those matched as typed before an inflected form; then by concept key
    (alphabetical, so an ambiguous alias such as "milk" lists its concepts
    in a fixed order); within a concept the matched canonicals before the
    siblings, then the preparation tie-break (the query's named state, else
    the locale's concept default, food_preparation.preferred_preparation)."""
    q = _normalise_query(query)
    forms = _alias_forms(q)
    rows = db.execute(
        select(CanonicalAlias, CanonicalFood)
        .join(CanonicalFood, CanonicalFood.id == CanonicalAlias.canonical_food_id)
        .where(
            func.lower(CanonicalAlias.alias).in_(forms),
            CanonicalAlias.locale.in_((locale, "*")),
            CanonicalFood.status == "active",
            CanonicalFood.default_food_id.isnot(None),
        )
    ).all()
    if not rows:
        return []

    matched: dict[int, tuple[tuple, CanonicalAlias, CanonicalFood]] = {}
    for alias, canonical in rows:
        rank = (alias.locale != locale, alias.alias.lower() != q, alias.relationship != "exact", alias.id)
        if canonical.id not in matched or rank < matched[canonical.id][0]:
            matched[canonical.id] = (rank, alias, canonical)
    concept_rank: dict[str, tuple] = {}
    for rank, _, canonical in matched.values():
        concept_rank[canonical.concept] = min(concept_rank.get(canonical.concept, rank[:2]), rank[:2])

    siblings = db.execute(
        select(CanonicalFood).where(
            CanonicalFood.concept.in_(list(concept_rank)),
            CanonicalFood.status == "active",
            CanonicalFood.default_food_id.isnot(None),
            CanonicalFood.id.notin_(list(matched)),
        )
    ).scalars().all()
    canonicals = [c for _, _, c in matched.values()] + list(siblings)
    foods = {f.id: f for f in db.query(Food).filter(Food.id.in_({c.default_food_id for c in canonicals})).all()}

    preferred_state = preferred_preparation(q, locale)

    def order(canonical: CanonicalFood) -> tuple:
        return (
            concept_rank[canonical.concept], canonical.concept, canonical.id not in matched,
            preparation_rank(canonical.preparation_state, preferred_state), canonical.key,
        )

    hits = []
    for canonical in sorted(canonicals, key=order):
        food = foods.get(canonical.default_food_id)
        if food is None:
            continue
        alias = matched[canonical.id][1] if canonical.id in matched else None
        name = (canonical.display_name_en_us if locale == EN_US else None) or canonical.display_name_en_gb
        hits.append(FoodSearchHit(
            food,
            canonical.preparation_state,
            preparation_label(canonical.preparation_state, locale),
            alias.alias if alias else q,
            relationship=alias.relationship if alias and alias.relationship != "exact" else None,
            note=alias.display_note if alias else None,
            canonical_key=canonical.key,
            canonical_name=name,
            canonical_source=_CANONICAL_SOURCE.get(food.data_type),
        ))
    return hits


def search_foods_by_name_hits(
    db: Session, query: str, limit: int = 20, locale: str | None = None
) -> list[FoodSearchHit]:
    """Ranked food-name search with per-result preparation state and any
    synonym note. See the block comment above for the design; the trigram
    fallback is described inline below."""
    query = query.strip()
    if len(query) < 2:
        return []
    locale = locale or search_locale()

    variants = expand_food_query(query, locale)
    generic_pool = max(limit * 10, _GENERIC_POOL_MIN)
    branded_pool = limit * _BRANDED_POOL_FACTOR
    not_branded = or_(Food.data_type.is_(None), Food.data_type != "branded_food")
    by_id: dict[int, Food] = {}
    # One SQL round per rank group, so a large literal reading ("chips")
    # cannot starve the preferred one ("french fried") out of the pool.
    # Shortest names first within each pool: closer to the query and a
    # cheap, index-free proxy for relevance.
    for rank in sorted({v.rank for v in variants}):
        condition = or_(*[_variant_condition(v) for v in variants if v.rank == rank])
        for type_filter, pool in ((not_branded, generic_pool), (Food.data_type == "branded_food", branded_pool)):
            rows = (
                db.query(Food)
                .filter(condition, type_filter)
                .order_by(func.length(Food.name), Food.name)
                .limit(pool)
                .all()
            )
            for food in rows:
                by_id.setdefault(food.id, food)

    hits = _collapse_branded_versions(_rank_hits(list(by_id.values()), variants, query, locale))
    canonical = _canonical_hits(db, query, locale)
    shown = {h.food.id for h in canonical}
    hits = (canonical + [h for h in hits if h.food.id not in shown])[:limit]

    # Typo tolerance only: the trigram fallback runs when the token pass
    # found nothing at all. It used to top up any short list, which put
    # unrelated rows under real matches (plan 1.2 cause 6: rapeseed oil ->
    # grapes, houmous -> kombucha) and cost seconds per query.
    if hits or db.bind is None or db.bind.dialect.name != "postgresql":
        return hits

    return _trigram_fallback(db, query, limit, locale)


def search_foods_by_name(db: Session, query: str, limit: int = 20, locale: str | None = None) -> list[Food]:
    """Synonym/plural-aware, token-AND name search, ranked by relevance —
    the food-name autocomplete used when logging a diary/meal-plan entry
    or building a recipe, and the fuzzy tier of stock-recipe ingredient
    matching. Falls back to PostgreSQL trigram similarity for typo
    tolerance when running against Postgres and nothing matched; see the
    module docstring for why that part is gated on the actual DB
    dialect."""
    return [hit.food for hit in search_foods_by_name_hits(db, query, limit, locale)]


def _trigram_fallback(db: Session, query: str, limit: int, locale: str) -> list[FoodSearchHit]:
    # `name % :q` (not a bare `similarity(name, :q) > threshold` filter) is
    # what actually lets Postgres serve this from ix_foods_name_trgm's GIN
    # index — pg_trgm's index support is keyed to the `%`/`<->` operators
    # specifically, not to an arbitrary function-call predicate, so the
    # previous form silently fell back to a full sequential scan on every
    # single call (found while profiling phytate-ingestion matching against
    # the real 1.4M-row catalog: ~8-12s per query). `SET LOCAL` scopes the
    # threshold to this transaction only, and reproduces the same 0.2 cutoff
    # the old query used, so match results are unchanged — this is a pure
    # index-usage fix, not a similarity-threshold/behaviour change.
    db.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.2"))
    fuzzy_rows = db.execute(
        text(
            "SELECT id FROM foods WHERE name % :q "
            "ORDER BY name <-> :q LIMIT :fetch_limit"
        ),
        {"q": query, "fetch_limit": limit * 2},
    ).fetchall()
    fuzzy_ids = [row[0] for row in fuzzy_rows]
    if not fuzzy_ids:
        return []
    fuzzy_foods_by_id = {f.id: f for f in db.query(Food).filter(Food.id.in_(fuzzy_ids)).all()}
    hits = []
    for food_id in fuzzy_ids:
        food = fuzzy_foods_by_id.get(food_id)
        if food is None:
            continue
        state = classify_preparation(food.name, food.data_type)
        hits.append(FoodSearchHit(food, state, preparation_label(state, locale), query.lower()))
    return _collapse_branded_versions(hits)[:limit]


def search_recipes_by_name(db: Session, user_id: int, query: str, limit: int = 20) -> list[Recipe]:
    """Name autocomplete for the recipe picker (logging a diary/meal-plan
    entry) — mirrors search_foods_by_name's synonym/plural-aware substring
    matching and relevance ranking, but over a different scope: a user's own
    recipes, recipes shared with them, and the public/stock catalogue,
    *not* just their own (see prompt 1.1 — the previous behaviour only ever
    searched `GET /api/recipes`, which is own-recipes-only, so it found
    nothing for a demo account or any user with few personal recipes).

    Own and shared recipes always rank ahead of public ones, regardless of
    textual relevance — searching your own catalogue first is what a
    returning user means by "search recipes" when they have matches there,
    and the public catalogue is the fallback when they don't. Within each
    tier, ranking is by the same exact/prefix/similarity heuristic
    search_foods_by_name uses.

    Own/shared matches are fetched without a pre-ranking cap (there are
    normally only a handful of either), so a real match there is never
    truncated away by an unrelated flood of public candidates; only the
    public tier is capped before ranking, same as search_foods_by_name caps
    its branded-food-dominated candidate pool. That cap is ordered
    exact-match-first, then prefix-match-first, then alphabetically (not
    plain alphabetical) — a public catalogue large enough to exceed the cap
    could otherwise let an exact/near-exact match get discarded before the
    real relevance ranking below ever sees it, just because its name sorts
    late alphabetically among the other substring matches."""
    query = query.strip()
    if len(query) < 2:
        return []

    terms = expand_query_terms(query)
    name_conditions = or_(*[Recipe.name.ilike(f"%{t}%") for t in terms])

    shared_recipe_ids = {
        row[0]
        for row in db.query(RecipeShare.recipe_id).filter(RecipeShare.shared_with_user_id == user_id).all()
    }

    own_or_shared_filter = or_(Recipe.user_id == user_id, Recipe.id.in_(shared_recipe_ids))
    own_or_shared = db.query(Recipe).filter(own_or_shared_filter, name_conditions).all()

    exact_match = case((Recipe.name.ilike(query), 0), else_=1)
    prefix_match = case((Recipe.name.ilike(f"{query}%"), 0), else_=1)
    public_candidates = (
        db.query(Recipe)
        .filter(Recipe.is_public.is_(True), Recipe.user_id != user_id, name_conditions)
        .order_by(exact_match, prefix_match, Recipe.name)
        .limit(limit * 5)
        .all()
    )

    query_lower = query.lower()

    def sort_key(recipe: Recipe) -> tuple:
        is_own_or_shared = recipe.user_id == user_id or recipe.id in shared_recipe_ids
        name_lower = recipe.name.lower()
        is_exact = name_lower == query_lower
        is_prefix = name_lower.startswith(query_lower)
        similarity = SequenceMatcher(None, query_lower, name_lower).ratio()
        return (not is_own_or_shared, not is_exact, not is_prefix, -similarity)

    candidates = own_or_shared + public_candidates
    return sorted(candidates, key=sort_key)[:limit]


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
