"""Preparation state of a food, read from its name.

This is the *simple* classifier that docs/plans/canonical-foods-plan.md
section 4 allows PR 1 to ship with; PR 3 replaces it with a fuller,
coverage-reported version. It is a pure function over the food's name
(FDC puts the state in the name text: "..., dry", "..., canned, drained
solids", "..., cooked, boiled, with salt") and is used for two things only:

  * a ranking tie-break in name search (never a filter: every row that
    matched the query is still returned), and
  * a label shown next to each search result, so dry and cooked rice, or
    dried and tinned chickpeas, are not confused when logging.

Known limits of this simple version (see the PR description):

  * Branded names often omit the state ("13 FOODS CHICKPEAS"). Those come
    back `unspecified`; nothing is guessed.
  * FDC calls dry pulses "mature seeds, raw" and dry rice "raw". The
    pulse/grain rules below map those to `dry`, but only for the heads
    listed in _DRY_GOODS_HEADS and names containing "mature seeds".
  * Words are matched, not parsed: "baked" means roasted/baked, so
    "Beans, baked, home prepared" is `roasted` (the tinned baked-bean rows
    are caught by "canned" first).
  * "dry mix" (a packet mix) is not `dry`; it stays `unspecified`.

The vocabulary is the closed list from the plan (section 3.1).
"""

from __future__ import annotations

import re

from .search_locale import EN_GB, EN_US

PREPARATION_STATES = (
    "unspecified",
    "raw",
    "dry",
    "soaked",
    "sprouted",
    "cooked_boiled",
    "canned_drained",
    "canned_with_liquid",
    "frozen",
    "roasted",
    "fried",
    "dehydrated",
)

# Heads (first word of the name, singular) whose "raw"/"uncooked"/no-state
# rows are, in practice, the dry product: dry pasta, uncooked rice, rolled
# oats, dry lentils.
_DRY_GOODS_HEADS = frozenset({
    "oat", "oats", "rice", "pasta", "spaghetti", "macaroni", "lentil", "lentils",
    "couscous", "quinoa", "barley", "bulgur",
})
# Heads whose plain "dried" means the dry pulse/grain/seed, not a
# dehydrated fruit/vegetable/herb ("Seeds, sesame seeds, whole, dried").
_PULSE_HEADS = frozenset({
    "chickpea", "chickpeas", "lentil", "lentils", "beans", "bean", "peas", "pea",
    "seeds", "seed", "nuts",
})


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def _head(name_lower: str) -> str:
    """The head noun when the first comma segment is a single word
    ("Rice, white, ..." -> "rice"; "Oats (Includes ...)" -> "oats"), else
    "" ("Rice crackers" is not rice)."""
    first_segment = name_lower.split(",", 1)[0].split("(", 1)[0]
    words = re.findall(r"[a-z]+", first_segment)
    return words[0] if len(words) == 1 else ""


def classify_preparation(name: str) -> str:
    """One state from PREPARATION_STATES for this food name. Order matters:
    the first matching rule wins (tinned before cooked, so "Beans, baked,
    canned" is tinned; fried before frozen, so frozen french fries are
    fried)."""
    n = name.lower()
    head = _head(n)
    is_pulse_or_grain = head in _DRY_GOODS_HEADS or head in _PULSE_HEADS or "mature seeds" in n

    if _has(r"\b(canned|tinned)\b", n):
        return "canned_drained" if _has(r"\bdrained\b", n) else "canned_with_liquid"
    if _has(r"\b(fried|french fries|fries)\b", n):
        return "fried"
    if _has(r"\b(cooked|boiled|simmered|steamed|stewed|microwaved|poached)\b", n):
        return "cooked_boiled"
    if _has(r"\b(roasted|baked|broiled|grilled|toasted)\b", n) or _has(r"oven[- ]heated", n):
        return "roasted"
    if _has(r"\bsprouted\b", n):
        return "sprouted"
    if _has(r"\bsoaked\b", n):
        return "soaked"
    if _has(r"\bfrozen\b", n):
        return "frozen"
    if _has(r"\bdehydrated\b", n):
        return "dehydrated"
    if _has(r"\bdried\b", n):
        return "dry" if is_pulse_or_grain else "dehydrated"
    if _has(r"\bdry\b(?! mix)", n) or _has(r"\buncooked\b", n):
        return "dry"
    if _has(r"\b(raw|fresh)\b", n):
        return "dry" if is_pulse_or_grain else "raw"
    if head in _DRY_GOODS_HEADS:
        return "dry"
    return "unspecified"


def preparation_family(state: str) -> str:
    """Tinned-drained and tinned-with-liquid are both 'tinned' for the
    purpose of a default ("tinned tomatoes" is happy with either)."""
    return "canned" if state.startswith("canned_") else state


_LABELS = {
    EN_GB: {
        "raw": "Raw", "dry": "Dry", "soaked": "Soaked", "sprouted": "Sprouted",
        "cooked_boiled": "Cooked", "canned_drained": "Tinned, drained",
        "canned_with_liquid": "Tinned", "frozen": "Frozen", "roasted": "Roasted/baked",
        "fried": "Fried", "dehydrated": "Dried",
    },
    EN_US: {
        "raw": "Raw", "dry": "Dry", "soaked": "Soaked", "sprouted": "Sprouted",
        "cooked_boiled": "Cooked", "canned_drained": "Canned, drained",
        "canned_with_liquid": "Canned", "frozen": "Frozen", "roasted": "Roasted/baked",
        "fried": "Fried", "dehydrated": "Dried",
    },
}
NOT_STATED_LABEL = "Preparation not stated"


def preparation_label(state: str, locale: str) -> str | None:
    """User-facing badge text, or None for `unspecified` (callers decide
    whether an unstated state is worth flagging; see search.py)."""
    return _LABELS.get(locale, _LABELS[EN_GB]).get(state)


# Words in a query that name a preparation state. When the user types one
# ("dried chickpeas", "cooked rice") it beats the concept default below.
# "baked"/"roasted" are deliberately absent: they are part of food names
# ("baked beans") far more often than a request for a state.
_QUERY_STATE_WORDS = {
    "canned": "canned_drained", "tinned": "canned_drained", "drained": "canned_drained",
    "dry": "dry", "dried": "dry", "uncooked": "dry",
    "cooked": "cooked_boiled", "boiled": "cooked_boiled",
    "raw": "raw", "fresh": "raw",
    "frozen": "frozen", "fried": "fried", "sprouted": "sprouted", "soaked": "soaked",
}

# Default preparation per concept for UK users (owner's decision, recorded
# in the PR 1 description). Used only as a ranking tie-break when the query
# names no state; never a filter and never hides other states. Keys are
# the query words (singular) that identify the concept; a multi-word key
# needs all its words in the query. Vegetables and fruit default to raw,
# which is the general tie-break already (raw/unspecified first), so they
# need no entry here.
DEFAULT_PREPARATION_BY_LOCALE: dict[str, list[tuple[tuple[str, ...], str]]] = {
    EN_GB: [
        (("chickpea",), "canned_drained"),
        (("garbanzo",), "canned_drained"),
        (("kidney", "bean"), "canned_drained"),
        (("baked", "bean"), "canned_drained"),
        (("tomato",), "canned_drained"),
        (("sweetcorn",), "canned_drained"),
        (("lentil",), "dry"),
        (("rice",), "dry"),
        (("pasta",), "dry"),
        (("porridge", "oat"), "dry"),
    ],
    EN_US: [],
}


def _singular(word: str) -> str:
    if word.endswith("oes") and len(word) > 4:  # tomatoes, potatoes
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def preferred_preparation(query: str, locale: str) -> str | None:
    """The state to prefer for this query: one the query names, else the
    locale's concept default, else None (meaning raw/unspecified first)."""
    words = [_singular(w) for w in re.findall(r"[a-z]+", query.lower())]
    for word in words:
        if word in _QUERY_STATE_WORDS:
            return _QUERY_STATE_WORDS[word]
    word_set = set(words)
    for concept_words, state in DEFAULT_PREPARATION_BY_LOCALE.get(locale, []):
        if all(w in word_set for w in concept_words):
            return state
    return None


def preparation_rank(state: str, preferred: str | None) -> int:
    """Lower sorts first. With no preference: raw/dry/unspecified (the
    state a food is bought in), then the rest. With one: the preferred
    state, then its family (tinned with liquid when tinned-drained was
    preferred), then raw/unspecified, then the rest."""
    if preferred is None:
        return 0 if state in ("raw", "dry", "unspecified") else 1
    neutral = state in ("raw", "unspecified")
    if state == preferred:
        return 0
    if preparation_family(state) == preparation_family(preferred):
        return 1
    return 2 if neutral else 3
