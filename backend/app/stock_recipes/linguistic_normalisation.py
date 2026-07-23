"""Pure text normalisation for a raw parsed ingredient name — no
nutritional/substitution judgement lives here at all (that's
ingredient_aliases.py + food_matching.py's job). Kept as its own module
(prompt section 10: "separate linguistic normalisation from nutritional
substitution") so it's obvious, from module boundaries alone, which part
of ingredient matching is "make the text comparable" and which part is
"decide what food this text means" — the same normalised text feeds the
ALIASES/REVIEWED_FALLBACKS lookup, the canonical Food.name match, and gets
handed to the fuzzy search tier, so all three tiers agree on what "the
same ingredient name" looks like before any of them makes a substitution
judgement about it.

This was previously part of food_matching.py itself; the split is a pure
move, not a behaviour change — see that module for the tiers that actually
decide what a normalised name resolves to.
"""

from __future__ import annotations

import re

# leading noise words stripped from a parsed ingredient name before
# matching — container/pack words the parser leaves in place (see
# ingredient_parser.py's docstring: it's honest about raw structure, not
# responsible for search normalisation) and quantity-adjacent leftovers.
LEADING_STOPWORDS = (
    "tin", "tins", "can", "cans", "packet", "packets", "jar", "jars",
    "block", "blocks", "bag", "bags", "bottle", "bottles",
)
_LEADING_STOPWORD_RE = re.compile(
    r"^(?:" + "|".join(LEADING_STOPWORDS) + r")\s+(?:of\s+)?", re.IGNORECASE,
)


def normalise_ingredient_name(name: str) -> str:
    """Lowercased, leading container words stripped, whitespace collapsed —
    NOT a full normal form (no stemming/synonym work; search_foods_by_name
    already does that for its own fuzzy tier). Used as the ALIASES/
    REVIEWED_FALLBACKS lookup key and as the deterministic-match query —
    purely textual, carries no opinion about which food anything means."""
    text = name.strip().lower()
    text = _LEADING_STOPWORD_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()
