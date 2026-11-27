"""Locale-aware vocabulary for food name search.

Three tables, all hand-written from docs/plans/canonical-foods-plan.md and
public USDA FoodData Central food names. Nothing here is derived from any
phytate source file.

FOOD_SYNONYMS
    The original symmetric list (aubergine<->eggplant, ...). Still used as
    is by recipe-name search; food search treats it as any-locale phrase
    synonyms.

PHRASE_SYNONYMS[locale][query]
    What a whole query means in that locale, as the words a matching food
    name must contain (in any order). Each entry carries the relationship
    (same vocabulary as stock_recipes/ingredient_aliases.py: exact,
    regional_equivalent, close_analogue, category_proxy) and an optional
    note that is shown next to every result the entry resolves to. A
    `preferred` entry wins over the literal query's own matches: under
    en-GB, "chips" means french fries, so taro chips still match "chips"
    but rank after the fries. Without `preferred`, the synonym's matches
    rank alongside the literal ones.

    The plan's data model for the relationship flag (canonical_alias, PR 4)
    is not in PR 1's scope, so the relationship and note live here, on the
    synonym entry, as text.

TOKEN_SYNONYMS[locale][word]
    Alternatives for one word inside any query, so "tinned tomatoes" finds
    "Tomatoes, crushed, canned" and "wholemeal bread" finds "Bread,
    whole-wheat". Only words that are unambiguous in the locale belong
    here; "chips" and "biscuit" are deliberately phrase-level only.

Locale "*" applies to every locale. Lookups are lowercase.
"""

from __future__ import annotations

from dataclasses import dataclass

from .search_locale import EN_GB

ANY_LOCALE = "*"

EXACT = "exact"
REGIONAL_EQUIVALENT = "regional_equivalent"
CLOSE_ANALOGUE = "close_analogue"
CATEGORY_PROXY = "category_proxy"
RELATIONSHIPS = frozenset({EXACT, REGIONAL_EQUIVALENT, CLOSE_ANALOGUE, CATEGORY_PROXY})

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


@dataclass(frozen=True)
class SearchSynonym:
    """A food name matches when it contains every entry of `words`
    (case-insensitive substrings, any order)."""

    words: tuple[str, ...]
    relationship: str = REGIONAL_EQUIVALENT
    note: str | None = None
    preferred: bool = False

    def __post_init__(self):
        if self.relationship not in RELATIONSHIPS:
            raise ValueError(f"unknown relationship {self.relationship!r}")
        if not self.words or any(not w.strip() for w in self.words):
            raise ValueError("a synonym needs at least one non-empty word")


def _s(*words: str, relationship: str = REGIONAL_EQUIVALENT, note: str | None = None,
       preferred: bool = False) -> SearchSynonym:
    return SearchSynonym(tuple(words), relationship, note, preferred)


SEMI_SKIMMED_NOTE = "approx. UK semi-skimmed"
# "reduced fat" keeps out "Milk, evaporated, 2% fat" and "Cheese, cottage,
# lowfat, 2% milkfat"
_semi_skimmed = (_s("milk", "reduced fat", "2%", relationship=CLOSE_ANALOGUE, note=SEMI_SKIMMED_NOTE),)
_skimmed = (_s("milk", "nonfat"),)
_porridge_oats = (_s("oats", "rolled", preferred=True),)
_crisps = (_s("potato chips", preferred=True),)
_chips = (_s("potato", "french fried", preferred=True), _s("french fries", preferred=True))
# A plain UK biscuit is closest to FDC's "Cookies, Marie biscuit"; any other
# cookie row follows it.
_biscuits = (
    _s("cookies", "marie biscuit", relationship=CLOSE_ANALOGUE, preferred=True),
    _s("cookie", preferred=True),
)

PHRASE_SYNONYMS: dict[str, dict[str, tuple[SearchSynonym, ...]]] = {
    ANY_LOCALE: {
        # whole phrases, as recipe-name search uses them ("green onion" must
        # appear as written, not "onions, green peppers")
        key: tuple(_s(value, relationship=REGIONAL_EQUIVALENT) for value in values)
        for key, values in FOOD_SYNONYMS.items()
    },
    EN_GB: {
        # Plan section 1.2 cause 4 and section 4 (PR 1) word list.
        "rocket": (_s("arugula", preferred=True),),
        "swede": (_s("rutabaga", preferred=True),),
        "crisps": _crisps,
        # en-GB chips are fries; en-US chips are crisps (no en-US entry, so
        # en-US keeps the literal meaning).
        "chips": _chips,
        "oven chips": _chips,
        # en-GB biscuit is a cookie; the US scone-like biscuit stays
        # reachable as the literal match, ranked after.
        "biscuit": _biscuits,
        "biscuits": _biscuits,
        "double cream": (_s(
            "cream", "heavy", relationship=CLOSE_ANALOGUE,
            note="UK double cream (~48% fat) is richer than US heavy cream (~36%)", preferred=True,
        ),),
        "single cream": (_s(
            "cream", "light", relationship=CLOSE_ANALOGUE, note="approx. UK single cream", preferred=True,
        ),),
        # phrases, not words: "sugar" + "granulated" would also match
        # "Sweeteners, sugar substitute, granulated"
        "caster sugar": (_s("granulated sugar"), _s("sugars, granulated")),
        "icing sugar": (_s("powdered sugar"), _s("sugars, powdered")),
        "plain flour": (_s("flour", "all-purpose"),),
        "self-raising flour": (_s("flour", "self-rising"),),
        "self raising flour": (_s("flour", "self-rising"),),
        "strong flour": (_s("flour", "bread"),),
        "strong white flour": (_s("flour", "bread"),),
        # Owner's decision: semi-skimmed maps to US 2% milk, flagged as a
        # close analogue (UK semi-skimmed is ~1.7% fat).
        "semi-skimmed milk": _semi_skimmed,
        "semi skimmed milk": _semi_skimmed,
        "semi-skimmed": _semi_skimmed,
        "semi skimmed": _semi_skimmed,
        "skimmed milk": _skimmed,
        "skimmed": _skimmed,
        # UK "mince" on its own is beef mince.
        "mince": (_s("beef", "ground", preferred=True),),
        "porridge oats": _porridge_oats,
        "porridge": (_s("oats", "cooked", preferred=True),),
        # UK baked beans are the vegetarian kind in tomato sauce; the FDC
        # row is US-made, so it is a close analogue, not the same product.
        "baked beans": (_s(
            "beans", "baked", "canned", "vegetarian", relationship=CLOSE_ANALOGUE,
            note="approx. UK baked beans", preferred=True,
        ),),
        "sweetcorn": (_s("corn", "sweet"),),
        "mangetout": (_s("peas", "edible-podded"),),
    },
}

TOKEN_SYNONYMS: dict[str, dict[str, tuple[str, ...]]] = {
    ANY_LOCALE: {
        "aubergine": ("eggplant",),
        "eggplant": ("aubergine",),
        "courgette": ("zucchini",),
        "zucchini": ("courgette",),
        "coriander": ("cilantro",),
        "cilantro": ("coriander",),
        "garbanzo": ("chickpea",),
        "chickpea": ("garbanzo",),
        "houmous": ("hummus", "hommous"),
        "hummus": ("houmous", "hommous"),
        "rapeseed": ("canola",),
        "canola": ("rapeseed",),
        "wholemeal": ("whole-wheat", "whole wheat", "whole-grain", "whole grain"),
        "beetroot": ("beet",),
        "sweetcorn": ("sweet corn", "corn, sweet"),
        "yoghurt": ("yogurt",),
        "yogurt": ("yoghurt",),
        "dried": ("dry",),
        # FDC names fresh produce "..., raw" ("Ginger root, raw") and
        # ground spices are often sold as "... POWDER"
        "fresh": ("raw",),
        "ground": ("powder",),
    },
    EN_GB: {
        "tinned": ("canned",),
        "canned": ("tinned",),
        "mince": ("minced", "ground"),
        "minced": ("mince", "ground"),
        "swede": ("rutabaga",),
        "semi-skimmed": ("semi skimmed",),
        "skimmed": ("skim", "nonfat"),
    },
}


def phrase_synonyms(phrase: str, locale: str) -> tuple[SearchSynonym, ...]:
    """Locale-specific entries first, then any-locale ones."""
    return PHRASE_SYNONYMS.get(locale, {}).get(phrase, ()) + PHRASE_SYNONYMS[ANY_LOCALE].get(phrase, ())


def token_synonyms(word: str, locale: str) -> tuple[str, ...]:
    return TOKEN_SYNONYMS.get(locale, {}).get(word, ()) + TOKEN_SYNONYMS[ANY_LOCALE].get(word, ())
