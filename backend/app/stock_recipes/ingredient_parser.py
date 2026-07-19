"""Parses a raw recipe ingredient line (as it appears on the source, e.g.
"500 g 5% lean beef mince" or "1 large onion (peeled and finely diced)")
into structured fields, without ever inventing a quantity that wasn't
stated.

The parser never raises on a malformed line — every line, however garbled,
comes back as a ParsedIngredient with raw_text preserved and a low
parsing_confidence, so a bad line can be reviewed/rejected downstream
rather than crashing the whole recipe's import.

Quantities are always a (min, max) pair, equal unless the line stated a
range ("2-3 tbsp"). A line with no stated amount at all ("Salt, to taste")
gets quantity_min = quantity_max = None — never a guessed number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PARSER_VERSION = "1.0.0"

# --- quantity parsing -------------------------------------------------

_UNICODE_FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1 / 3, "⅔": 2 / 3,
    "⅕": 0.2, "⅖": 0.4, "⅗": 0.6, "⅘": 0.8,
    "⅙": 1 / 6, "⅚": 5 / 6,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
_UNICODE_FRACTION_CHARS = "".join(_UNICODE_FRACTIONS)

# a single number: mixed unicode fraction ("1½"), ascii mixed fraction
# ("1 1/2"), plain fraction ("1/2"), lone unicode fraction ("½"), decimal
# ("1.5"), or integer ("2")
_NUM = (
    rf"(?:\d+\s+\d+/\d+"  # mixed ascii fraction: "1 1/2"
    rf"|\d+[{_UNICODE_FRACTION_CHARS}]"  # mixed unicode fraction: "1½"
    rf"|\d+/\d+"  # plain fraction: "1/2"
    rf"|[{_UNICODE_FRACTION_CHARS}]"  # lone unicode fraction: "½"
    rf"|\d+\.\d+"  # decimal: "1.5"
    rf"|\d+)"  # integer: "2"
)
_RANGE_SEP = r"(?:\s*[-–]\s*|\s+to\s+)"
_QUANTITY_RE = re.compile(rf"^\s*({_NUM})(?:{_RANGE_SEP}({_NUM}))?\s*", re.IGNORECASE)


def _parse_number(token: str) -> float:
    token = token.strip()
    if token in _UNICODE_FRACTIONS:
        return _UNICODE_FRACTIONS[token]
    # mixed unicode fraction, e.g. "1½"
    if len(token) > 1 and token[-1] in _UNICODE_FRACTIONS:
        return float(token[:-1]) + _UNICODE_FRACTIONS[token[-1]]
    # mixed ascii fraction, e.g. "1 1/2"
    if " " in token:
        whole, frac = token.split(" ", 1)
        num, den = frac.split("/")
        return float(whole) + float(num) / float(den)
    if "/" in token:
        num, den = token.split("/")
        return float(num) / float(den)
    return float(token)


# --- units --------------------------------------------------------------

# canonical unit -> aliases (matched case-insensitively, longest-first so
# e.g. "tablespoons" matches before "tbsp" ambiguity never arises)
UNIT_ALIASES: dict[str, list[str]] = {
    "g": ["g", "gram", "grams", "gramme", "grammes"],
    "kg": ["kg", "kilogram", "kilograms", "kilo", "kilos"],
    "ml": ["ml", "millilitre", "millilitres", "milliliter", "milliliters"],
    "l": ["l", "litre", "litres", "liter", "liters"],
    "tsp": ["tsp", "teaspoon", "teaspoons", "tsps"],
    "tbsp": ["tbsp", "tablespoon", "tablespoons", "tbsps", "tbs"],
    "oz": ["oz", "ounce", "ounces"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "tin": ["tin", "tins", "can", "cans"],
    "packet": ["packet", "packets", "pack", "packs", "pkt"],
    "jar": ["jar", "jars"],
    "clove": ["clove", "cloves"],
    "slice": ["slice", "slices"],
    "piece": ["piece", "pieces", "pc", "pcs"],
    "sprig": ["sprig", "sprigs"],
    "bunch": ["bunch", "bunches"],
    "handful": ["handful", "handfuls"],
    "pinch": ["pinch", "pinches"],
    "cup": ["cup", "cups"],
    "stick": ["stick", "sticks"],
    "block": ["block", "blocks"],
    "head": ["head", "heads"],
    "bulb": ["bulb", "bulbs"],
    "knob": ["knob", "knobs"],
    "dash": ["dash", "dashes"],
    "splash": ["splash", "splashes"],
}
_ALIAS_TO_UNIT: dict[str, str] = {
    alias.lower(): unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases
}
# longest alias first so multi-word/longer aliases aren't shadowed by a
# shorter prefix match
_UNIT_ALIAS_ALT = "|".join(sorted((re.escape(a) for a in _ALIAS_TO_UNIT), key=len, reverse=True))
_UNIT_TOKEN_RE = re.compile(rf"^({_UNIT_ALIAS_ALT})\b\.?\s*", re.IGNORECASE)

# "2 x 400g" multipack notation, common in UK recipes ("2 x 400g tins
# chopped tomatoes") — total mass is n * each-pack-size, not n alone
_MULTIPACK_RE = re.compile(rf"^\s*(\d+)\s*[x×]\s*({_NUM})\s*", re.IGNORECASE)

# the same idea without an "x" ("1  400g tin kidney beans...", seen in
# real fetched recipes) — deliberately much narrower than the "x" form:
# the second number must be a plain integer/decimal (not a fraction, which
# would make "1 1/2 cups" ambiguous with this) glued with NO space to the
# unit ("400g", never "400 g"), since that's what actually distinguishes
# "one 400g tin" from a genuine two-number phrase
_IMPLICIT_MULTIPACK_RE = re.compile(
    rf"^\s*(\d+)\s+(\d+(?:\.\d+)?)({_UNIT_ALIAS_ALT})\b\.?\s*", re.IGNORECASE
)

# a dual metric/imperial annotation immediately after the primary unit
# ("400g/14oz can...") — the imperial equivalent is discarded, the metric
# quantity+unit already captured is kept as the source of truth
_ALT_UNIT_STRIP_RE = re.compile(rf"^/\s*{_NUM}\s*({_UNIT_ALIAS_ALT})\b\.?\s*", re.IGNORECASE)

# textual-quantity idioms with no leading number ("a pinch of salt", "a
# large knob of butter") — rewritten to "1 <unit> of ..." so the normal
# quantity/unit parse below handles them uniformly
_ARTICLE_UNIT_RE = re.compile(
    r"^an?\s+(?:small\s+|large\s+|generous\s+|good\s+)?"
    r"(pinch|handful|knob|dash|splash)(?:es)?\s+of\s+",
    re.IGNORECASE,
)
# "juice of 1 lemon" / "zest of 2 limes" — rewritten so the count applies
# to the fruit, and "juice"/"zest" is folded into the ingredient name
_JUICE_ZEST_RE = re.compile(r"^(juice|zest)\s+of\s+", re.IGNORECASE)

_OPTIONAL_RE = re.compile(r"\(?\boptional\b\)?", re.IGNORECASE)
_TO_TASTE_RE = re.compile(r"\bto\s+taste\b", re.IGNORECASE)
_TO_SERVE_RE = re.compile(r"^\s*(?:to\s+serve\s*[:,]?\s*|,?\s*to\s+serve\s*)$|,\s*to\s+serve\b", re.IGNORECASE)
_PLUS_EXTRA_RE = re.compile(r",?\s*plus\s+extra\b[^,()]*", re.IGNORECASE)
_DIVIDED_RE = re.compile(r",?\s*divided\b", re.IGNORECASE)
_PAREN_RE = re.compile(r"\(([^()]*)\)")


@dataclass
class ParsedIngredient:
    raw_text: str
    quantity_min: float | None
    quantity_max: float | None
    unit: str | None  # canonical UNIT_ALIASES key, or None for a bare count ("2 eggs")
    name: str
    prep_note: str | None
    optional: bool
    alternatives: list[str] = field(default_factory=list)
    section: str | None = None
    parsing_confidence: float = 1.0

    @property
    def normalised_quantity(self) -> float | None:
        """Midpoint of (min, max) — what unit_conversion.py converts to
        grams. None when the line stated no amount at all."""
        if self.quantity_min is None or self.quantity_max is None:
            return None
        return (self.quantity_min + self.quantity_max) / 2


def _looks_like_section_header(line: str) -> bool:
    """Heuristic for a bare section heading among a flat ingredient list
    ("For the sauce", "To garnish:") — no digits, short, often ends with a
    colon. Never matches a real ingredient line, which always has either a
    leading quantity or is a bare "salt"/"pepper"-style unquantified item
    (those are still just the item, not a heading, so this additionally
    requires the line to end with ':' OR start with a known heading word)."""
    stripped = line.strip().rstrip(":").strip()
    if not stripped or any(ch.isdigit() for ch in stripped):
        return False
    if len(stripped.split()) > 6:
        return False
    starts_heading = bool(re.match(r"^(for|to)\b", stripped, re.IGNORECASE))
    ends_colon = line.strip().endswith(":")
    return starts_heading or ends_colon


def parse_ingredient_line(raw: str, section: str | None = None) -> ParsedIngredient:
    """Parses a single ingredient line. Never raises — a line this can't
    make sense of comes back with quantity=None, name=the cleaned raw text,
    and a low parsing_confidence, rather than blowing up the whole import."""
    original = raw
    confidence = 1.0
    text = raw.strip()
    if not text:
        return ParsedIngredient(original, None, None, None, "", None, False, section=section, parsing_confidence=0.0)

    optional = bool(_OPTIONAL_RE.search(text)) or bool(_TO_TASTE_RE.search(text)) or bool(_TO_SERVE_RE.search(text))
    text = _OPTIONAL_RE.sub("", text)

    notes: list[str] = []
    to_serve_match = _TO_SERVE_RE.search(text)
    if to_serve_match:
        notes.append("to serve")
        text = _TO_SERVE_RE.sub("", text)
    plus_extra_match = _PLUS_EXTRA_RE.search(text)
    if plus_extra_match:
        notes.append(plus_extra_match.group(0).strip(" ,"))
        text = _PLUS_EXTRA_RE.sub("", text)
    if _DIVIDED_RE.search(text):
        notes.append("divided")
        text = _DIVIDED_RE.sub("", text)
    if _TO_TASTE_RE.search(text):
        notes.append("to taste")
        text = _TO_TASTE_RE.sub("", text)

    # parenthetical prep notes — pull all of them out, keep the rest of the
    # line intact around each removed span
    paren_notes = [m.strip() for m in _PAREN_RE.findall(text) if m.strip()]
    notes = paren_notes + notes
    text = _PAREN_RE.sub("", text).strip()
    text = re.sub(r"\s{2,}", " ", text).strip(" ,")

    # "juice of 1 lemon" / "zest of 2 limes" -> count applies to the fruit,
    # "juice"/"zest" folds into the name once parsing below finishes
    juice_zest_suffix = None
    juice_zest_match = _JUICE_ZEST_RE.match(text)
    if juice_zest_match:
        juice_zest_suffix = juice_zest_match.group(1).lower()
        text = text[juice_zest_match.end():].strip()

    # "a pinch of salt" -> "1 pinch of salt", so the normal quantity/unit
    # parse below handles it the same as an explicit "1 pinch of salt"
    text = _ARTICLE_UNIT_RE.sub(lambda m: f"1 {m.group(1).lower()} of ", text)

    quantity_min = quantity_max = None
    unit: str | None = None

    implicit_match = _IMPLICIT_MULTIPACK_RE.match(text)
    if implicit_match:
        try:
            count = _parse_number(implicit_match.group(1))
            each = _parse_number(implicit_match.group(2))
            quantity_min = quantity_max = count * each
            unit = _ALIAS_TO_UNIT[implicit_match.group(3).lower()]
            text = text[implicit_match.end():].strip()
        except (ValueError, ZeroDivisionError):
            quantity_min = quantity_max = None

    multipack_match = None if quantity_min is not None else _MULTIPACK_RE.match(text)
    if multipack_match:
        remainder = text[multipack_match.end():]
        unit_match = _UNIT_TOKEN_RE.match(remainder)
        if unit_match:
            try:
                count = _parse_number(multipack_match.group(1))
                each = _parse_number(multipack_match.group(2))
                quantity_min = quantity_max = count * each
                unit = _ALIAS_TO_UNIT[unit_match.group(1).lower()]
                text = remainder[unit_match.end():].strip()
            except (ValueError, ZeroDivisionError):
                quantity_min = quantity_max = None

    if quantity_min is None:
        qty_match = _QUANTITY_RE.match(text)
        if qty_match:
            try:
                quantity_min = _parse_number(qty_match.group(1))
                quantity_max = _parse_number(qty_match.group(2)) if qty_match.group(2) else quantity_min
            except (ValueError, ZeroDivisionError):
                quantity_min = quantity_max = None
                confidence -= 0.4
            text = text[qty_match.end():].strip()
        else:
            # no leading quantity at all ("Salt", "Salt, to taste")
            confidence -= 0.15 if not optional else 0.0

        if quantity_min is not None:
            unit_match = _UNIT_TOKEN_RE.match(text)
            if unit_match:
                unit = _ALIAS_TO_UNIT[unit_match.group(1).lower()]
                text = text[unit_match.end():].strip()
            # else: a bare count ("2 onions", "3 eggs") — legitimate, no penalty

    if unit is not None:
        # discard a dual metric/imperial annotation right after the unit
        # ("400g/14oz can...") — the metric figure already captured is kept
        text = _ALT_UNIT_STRIP_RE.sub("", text)

    # a leading "of" after a unit/quantity-less lead-in ("a pinch of salt")
    text = re.sub(r"^of\s+", "", text, flags=re.IGNORECASE)

    # ingredient alternatives: "butter or olive oil" — split on a top-level
    # " or " (the ingredient text has already had parens/notes stripped, so
    # remaining " or " occurrences are between ingredient names, not prep
    # alternatives like "sliced or grated", which live inside the notes
    # already pulled out above)
    alternatives: list[str] = []
    or_split = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    if len(or_split) > 1:
        text = or_split[0].strip()
        alternatives = [a.strip() for a in or_split[1:] if a.strip()]

    # a first comma still in the name is a trailing prep note ("onion,
    # finely diced") that wasn't parenthesised
    if "," in text:
        name_part, _, trailing = text.partition(",")
        if trailing.strip():
            notes.append(trailing.strip())
        text = name_part.strip()

    name = text.strip(" .")
    if not name:
        confidence -= 0.3
        name = raw.strip()
    elif juice_zest_suffix:
        name = f"{name} {juice_zest_suffix}"

    prep_note = "; ".join(n for n in notes if n) or None
    confidence = max(0.0, min(1.0, confidence))

    return ParsedIngredient(
        raw_text=original,
        quantity_min=quantity_min,
        quantity_max=quantity_max,
        unit=unit,
        name=name,
        prep_note=prep_note,
        optional=optional,
        alternatives=alternatives,
        section=section,
        parsing_confidence=round(confidence, 3),
    )


def parse_ingredient_lines(lines: list[str]) -> list[ParsedIngredient]:
    """Parses a full ingredient list, tracking section headings ("For the
    sauce:") that some sources interleave as plain strings among the
    ingredient lines rather than as separate structured data."""
    results: list[ParsedIngredient] = []
    current_section: str | None = None
    for line in lines:
        if not line or not line.strip():
            continue
        if _looks_like_section_header(line):
            current_section = line.strip().rstrip(":").strip()
            continue
        results.append(parse_ingredient_line(line, section=current_section))
    return results
