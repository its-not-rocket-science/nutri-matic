"""Preparation state of a food, read from its name.

The classifier of docs/plans/canonical-foods-plan.md section 4, PR 3: a
pure function over the food's name (FDC puts the state in the name text:
"..., dry", "..., canned, drained solids", "..., cooked, boiled, with
salt"). Today it is used for two things only:

  * a ranking tie-break in name search (never a filter: every row that
    matched the query is still returned), and
  * a label shown next to each search result, so dry and cooked rice, or
    dried and tinned chickpeas, are not confused when logging.

The canonical-foods loader (app.canonical_foods.loader) also uses it for
the plan 3.1 invariant: an anchor or member's state must equal its
canonical food's. A canonical food is never `unknown`; it is `unspecified`
only where preparation does not apply (milk, cheddar), so a row whose
state is not stated cannot join a canonical that has one. So it is tuned for precision
over recall: where a name does not clearly state one preparation, it says
`unspecified` (no cue) or `unknown` (ambiguous), never a guess.

Tests: tests/test_food_preparation.py, against a hand-labelled fixture of
real FDC names (tests/fixtures/preparation_labelled.json). Coverage over a
real catalogue: `python -m app.preparation_coverage_report` (read-only).

How names are read:

  * Generic (Foundation/SR Legacy) names are "Head, modifier, ..." and the
    rules below read them directly.
  * Branded names are manufacturer text. Pass `data_type="branded_food"`:
    "fresh", "braised" and "sauteed" are then ignored (mostly brand names
    or one component of a ready meal), and a component-prone state
    (roasted, dried, dry, sprouted, soaked) in a composite product's name
    ("HONEY ROASTED PECAN GELATO", "... BREAD") is `unknown`.
  * FDC calls dry pulses "mature seeds, raw" and dry rice "raw", but also
    calls fresh legumes "raw" ("Peas, green, raw"). "raw" is `dry` only
    with a mature-seeds/split cue or a grain/rice/pasta/oats/lentil head; a
    fresh cue (green, snap, immature, edible-podded, pods, sweet, ...)
    keeps `raw`; a pulse name with neither is `unknown`.
  * "uncooked" is `raw` for meat and fish, `dry` for everything else.
  * A name giving two alternatives ("Durian, raw or frozen") is `unknown`.

Known limits:

  * Branded names often omit the state ("13 FOODS CHICKPEAS"): those stay
    `unspecified`. Only about 6% of branded rows state one.
  * Words are matched, not parsed: "baked" means roasted/baked, so
    "Beans, baked, home prepared" is `roasted` (the tinned rows are caught
    by "canned" first; the phrase "baked beans" is a dish, not a state).
  * "dry mix" (a packet mix), "dry-cured", "dry salami" and "dry rub" are
    not `dry`. "kettle cooked" crisps are not cooked.
  * Processing such as smoked, cured or pickled is not a preparation state
    in the vocabulary; those rows stay `unspecified`.

The vocabulary is the closed list from the plan (section 3.1), plus
`unknown` for names too ambiguous to classify.
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
    # Not in the plan's 3.1 list: the name is ambiguous ("Chickpeas, raw"
    # could be the dry pulse or a fresh one). Gets no badge and no
    # preparation tie-break, rather than a guessed state.
    "unknown",
)
# States that say nothing about how the food was prepared. No badge, no
# tie-break. A row in one of these can only join a canonical food whose own
# state is `unspecified` (preparation does not apply); see the module
# docstring.
UNCLASSIFIED_STATES = ("unspecified", "unknown")

# Heads (first comma segment, when it is a single word) whose
# "raw"/"uncooked"/no-state rows are, in practice, the dry product: dry
# pasta, uncooked rice and grains, rolled oats, dry lentils. Lentils are
# only sold dry, so they sit here rather than with the other pulses.
_DRY_GOODS_HEADS = frozenset({
    "oat", "oats", "rice", "pasta", "spaghetti", "macaroni", "lentil", "lentils",
    "couscous", "quinoa", "barley", "bulgur", "millet", "sorghum", "teff", "spelt",
    "farro", "amaranth", "buckwheat", "khorasan", "freekeh",
})
# Multi-word first segments that are the same kind of dry good.
_DRY_GOODS_SEGMENTS = frozenset({"wild rice", "amaranth grain", "buckwheat groats"})
# Heads whose plain "dried" means the dry pulse/grain/seed, not a
# dehydrated fruit/vegetable/herb ("Seeds, sesame seeds, whole, dried").
# Not used for "raw": see _RAW_PULSE_HEADS.
_PULSE_HEADS = frozenset({
    "chickpea", "chickpeas", "lentil", "lentils", "beans", "bean", "peas", "pea",
    "seeds", "seed", "nuts",
})
# Pulse heads whose "raw" rows can be either the dry pulse ("Beans, kidney,
# all types, mature seeds, raw") or a fresh vegetable ("Beans, snap, green,
# raw"; "Peas, green, raw"). Raw becomes dry only with an explicit mature or
# split cue; a fresh cue keeps raw; neither means unknown.
_RAW_PULSE_HEADS = frozenset({
    "chickpea", "chickpeas", "garbanzo", "beans", "bean", "peas", "pea", "soybeans", "soybean",
})
_DRY_PULSE_CUE = r"\bmature seeds?\b|\bsplit\b"
_FRESH_CUE = r"\b(immature|green|snap|edible-podded|sprouted|pods?|fresh|sweet)\b"
# "uncooked" means raw for meat and fish, dry for everything else FDC
# calls uncooked (grains, pasta, dried fruit).
_MEAT_WORDS = (
    r"\b(beef|pork|lamb|veal|chicken|turkey|duck|goose|meat|sausages?|patty|patties|"
    r"bacon|ham|fish|salmon|tuna|cod|shrimp|prawns?|seafood|steaks?|fillets?|breasts?|thighs?|wings?)\b"
)
# Words a name uses for two alternative states ("Durian, raw or frozen"):
# the row is either, so it is not classified.
_ALTERNATIVE_STATES = r"\b(raw|fresh) or (frozen|cooked)\b|\b(frozen|cooked) or (raw|fresh)\b"

# Branded names (manufacturer text, not FDC's "Head, modifier" form) often
# use a preparation word for one component or a flavour, not the product:
# "HONEY ROASTED PECAN GELATO", "TRES LECHES SPONGE CAKE SOAKED IN ...",
# "SNACK MIX ... DRIED CINNAMON APPLES", "SPROUTED GRAINS BREAD". When a
# branded name has one of these markers of a composite product, the
# component-prone cues below give `unknown` rather than a guessed state.
_COMPOSITE_MARKERS = (
    r"\b(with|and|mix|blend|clusters|trail|salad|sauce|spread|pesto|dip|bars?|cakes?|"
    r"cookies?|bread|breads|rolls?|buns?|cereal|granola|crackers|pizza|soup|gelato|ice cream|"
    r"yogurt|bites|snacks?|kit|meal|dinner|entree|sandwich|wrap|burrito|crust|waffles?|"
    r"butter|chips|crisps|puree|flour)\b|&|\+"
)
_COMPONENT_PRONE = frozenset({"roasted", "soaked", "sprouted", "dehydrated", "dry"})


def _raw_state(name_lower: str, head: str, segment: str) -> str:
    """What an explicit "raw"/"fresh" means for this name: a mature/split
    cue, or a cereal/rice/pasta/oats/lentil head, means the dry product
    ("Rice, white, long-grain, raw" is uncooked rice); otherwise a fresh
    cue keeps raw; a pulse with neither is unknown. Names saying dry/dried
    never get here (earlier rules catch them)."""
    dry_goods = head in _DRY_GOODS_HEADS or segment in _DRY_GOODS_SEGMENTS
    if dry_goods and not _has(r"\braw\b", name_lower):
        # "Pasta, fresh-refrigerated": fresh pasta is neither raw nor dry
        return "unknown"
    if _has(_DRY_PULSE_CUE, name_lower) or dry_goods:
        return "dry"
    if _has(_FRESH_CUE, name_lower):
        return "raw"
    if head in _RAW_PULSE_HEADS:
        return "unknown"
    return "raw"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


def _first_segment(name_lower: str) -> str:
    return name_lower.split(",", 1)[0].split("(", 1)[0].strip()


def _head(name_lower: str) -> str:
    """The head noun when the first comma segment is a single word
    ("Rice, white, ..." -> "rice"; "Oats (Includes ...)" -> "oats"), else
    "" ("Rice crackers" is not rice)."""
    words = re.findall(r"[a-z]+", _first_segment(name_lower))
    return words[0] if len(words) == 1 else ""


def _generic_state(n: str) -> str:
    """The rules for a name, before the branded-name check. Order matters:
    the first matching rule wins (tinned before cooked, so "Beans, baked,
    canned" is tinned; fried before frozen, so frozen french fries are
    fried)."""
    # "BAKED BEANS" names a dish (usually tinned), not a roasting method
    n = re.sub(r"\bbaked beans?\b", "beans", n)
    head = _head(n)
    segment = _first_segment(n)
    is_pulse_or_grain = (
        head in _DRY_GOODS_HEADS or head in _PULSE_HEADS or segment in _DRY_GOODS_SEGMENTS or "mature seeds" in n
    )

    if _has(_ALTERNATIVE_STATES, n):
        return "unknown"
    if _has(r"\b(canned|tinned)\b", n):
        return "canned_drained" if _has(r"\bdrained\b", n) else "canned_with_liquid"
    if _has(r"\b(fried|french fries|fries|sauteed|sautéed)\b", n):
        return "fried"
    if _has(r"\bkettle[- ]cooked\b", n):
        # a crisp-making method, not "cooked" in the meal sense
        return "unspecified"
    if _has(r"\b(cooked|boiled|simmered|steamed|stewed|braised|microwaved|poached)\b", n):
        return "cooked_boiled"
    if head in ("cereals", "oats", "oat") and _has(r"\bprepared with\b", n):
        # "Cereals, oats, instant, ..., prepared with water" is porridge
        return "cooked_boiled"
    if _has(r"\b(roasted|baked|broiled|grilled|toasted)\b", n) or _has(r"oven[- ]heated|\bpan-broil", n):
        return "roasted"
    if _has(r"\bsprouted\b", n):
        return "sprouted"
    if _has(r"\bsoaked\b", n):
        return "soaked"
    if _has(r"\bfrozen\b", n):
        return "frozen"
    if _has(r"\b(dehydrated|freeze[- ]dried)\b", n):
        return "dehydrated"
    if _has(r"\bdried\b", n):
        return "dry" if is_pulse_or_grain else "dehydrated"
    if _has(r"\buncooked\b", n):
        return "raw" if _has(_MEAT_WORDS, n) else "dry"
    if _has(r"\bdry\b(?! mix)(?!-cured| cured| salam)(?!\s*-?\s*rub)", n):
        return "dry"
    if _has(r"\b(raw|fresh)\b", n):
        return _raw_state(n, head, segment)
    if head in _DRY_GOODS_HEADS or segment in _DRY_GOODS_SEGMENTS:
        return "dry"
    return "unspecified"


def classify_preparation(name: str, data_type: str | None = None) -> str:
    """One state from PREPARATION_STATES for this food name.

    `data_type` is the FDC data type when known. Branded names get two
    extra rules (see _COMPOSITE_MARKERS): "fresh" is ignored, because it is
    mostly part of a brand ("Fresh Express", "Taylor Fresh Foods"), and a
    component-prone state in a composite product's name is `unknown`.
    Without `data_type` the name is read as an FDC generic name."""
    n = name.lower()
    if data_type != "branded_food":
        return _generic_state(n)

    # "Fresh" in a branded name is a brand or a claim, not a state
    # ("FRESH FROZEN" keeps its frozen). "Braised"/"sauteed" in a branded
    # name usually describe one component of a ready meal or sauce
    # ("SAUTEED ONION & MUSHROOM SAUCE"), so they are only read in FDC
    # generic names.
    n = re.sub(r"\b(fresh(ly)?|braised|saut[eé]ed)\b", " ", n)
    state = _generic_state(n)
    if state in _COMPONENT_PRONE:
        # "ROASTED & SALTED MIXED NUTS" is one product, not a composite
        plain = re.sub(r"\b(?:lightly |un)?salted\s*(?:&|and)\s*|\s*(?:&|and)\s*(?:lightly |un)?salted\b", " ", n)
        if _has(_COMPOSITE_MARKERS, plain):
            return "unknown"
    return state


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
    """User-facing badge text, or None for `unspecified` and `unknown`
    (callers decide whether an unstated state is worth flagging; see
    search.py, which never flags `unknown`)."""
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
    if state == "unknown":
        # no tie-break: level with an unstated state, neither promoted nor
        # demoted by a guessed preparation
        return 0 if preferred is None else 2
    if preferred is None:
        return 0 if state in ("raw", "dry", "unspecified") else 1
    neutral = state in ("raw", "unspecified")
    if state == preferred:
        return 0
    if preparation_family(state) == preparation_family(preferred):
        return 1
    return 2 if neutral else 3
