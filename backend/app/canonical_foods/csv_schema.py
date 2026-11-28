"""Parsing and validation of the reviewed canonical-foods CSV (plan 3.4).

Pure: no database. Run in CI by tests/test_canonical_foods.py and before
every load by app.canonical_foods.loader. Every problem in the file is
collected and reported at once, and any problem means nothing loads.

File: one row per alias. The canonical-level columns (concept,
preparation state, display names, anchor) repeat on every alias row of
the same canonical_key and must agree.

    concept             lowercase slug, groups preparation variants
    canonical_key       exactly "<concept>.<preparation_state>"
    preparation_state   models.CANONICAL_PREPARATION_STATES (never "unknown")
    display_name_en_gb  shown to en-GB users
    display_name_en_us  optional
    anchor_fdc_id       FDC id of the SR Legacy/Foundation row logged when
                        this canonical is chosen (keys use fdc_id, not
                        foods.id, so the file survives a re-import)
    alias               lowercase search term
    alias_locale        en-GB | en-US | *
    relationship        exact | regional_equivalent | close_analogue |
                        category_proxy (same vocabulary as
                        stock_recipes/ingredient_aliases.py)
    alias_note          user-facing note; required for close_analogue and
                        category_proxy
    ambiguous           "yes" lets one (locale, alias) point at more than
                        one concept; otherwise blank
    reviewer            who signed the row off; never blank or PENDING
    review_date         ISO date of that sign-off (blank while PENDING)
    notes               free-text review notes, not shown to users

A reviewer previewing a draft can parse it with require_signoff=False
(`validate --allow-unsigned`, `load --dry-run --allow-unsigned`). Nothing
that writes for real accepts that: the data migration and a plain `load`
always require sign-off.

The file holds only FDC identifiers and names plus hand-written terms. It
must never be seeded from any phytate review file (plan 1.5 #7).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..models import CANONICAL_ALIAS_LOCALES, CANONICAL_ALIAS_RELATIONSHIPS, CANONICAL_PREPARATION_STATES

CSV_PATH = Path(__file__).resolve().parent / "canonical_foods_en_gb.csv"

COLUMNS = (
    "concept", "canonical_key", "preparation_state", "display_name_en_gb", "display_name_en_us",
    "anchor_fdc_id", "alias", "alias_locale", "relationship", "alias_note", "ambiguous",
    "reviewer", "review_date", "notes",
)
PENDING_REVIEWER = "PENDING"
NOTE_REQUIRED = frozenset({"close_analogue", "category_proxy"})
_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")


class CanonicalCsvError(ValueError):
    """The file is invalid. `problems` lists every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in canonical foods CSV:\n" + "\n".join(problems))


@dataclass(frozen=True)
class AliasRow:
    alias: str
    locale: str
    relationship: str
    note: str | None
    ambiguous: bool
    reviewer: str
    review_date: date | None
    line: int


@dataclass
class CanonicalRow:
    key: str
    concept: str
    preparation_state: str
    display_name_en_gb: str
    display_name_en_us: str | None
    anchor_fdc_id: int
    aliases: list[AliasRow] = field(default_factory=list)


def file_sha256(path: Path = CSV_PATH) -> str:
    """Checksum of the file's bytes, line endings normalised to \\n so a
    Windows checkout gives the same value as CI. The data migration pins it."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def parse(text: str, *, today: date | None = None, require_signoff: bool = True) -> dict[str, CanonicalRow]:
    """Canonical rows by key. Raises CanonicalCsvError listing every problem.
    require_signoff=False accepts PENDING rows (blank date) for previews only."""
    today = today or date.today()
    problems: list[str] = []
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise CanonicalCsvError([f"header must be exactly: {','.join(COLUMNS)}"])

    canonicals: dict[str, CanonicalRow] = {}
    seen_alias: set[tuple[str, str, str]] = set()
    for line, raw in enumerate(reader, start=2):
        where = f"line {line}"
        if None in raw or None in raw.values():
            problems.append(f"{where}: wrong number of fields (an unquoted comma?)")
            continue
        row = {k: v.strip() for k, v in raw.items()}

        def bad(message: str, where: str = where) -> None:
            problems.append(f"{where}: {message}")

        concept, key, state = row["concept"], row["canonical_key"], row["preparation_state"]
        if not _SLUG.match(concept):
            bad(f"concept {concept!r} must be a lowercase slug")
        if state not in CANONICAL_PREPARATION_STATES:
            bad(f"preparation_state {state!r} is not one of {', '.join(CANONICAL_PREPARATION_STATES)}")
        if key != f"{concept}.{state}":
            bad(f"canonical_key {key!r} must be {concept}.{state!r}")
        if not row["display_name_en_gb"]:
            bad("display_name_en_gb is required")
        try:
            anchor = int(row["anchor_fdc_id"])
            if anchor <= 0:
                raise ValueError
        except ValueError:
            bad(f"anchor_fdc_id {row['anchor_fdc_id']!r} must be a positive FDC id")
            anchor = 0

        alias = row["alias"]
        if not alias or alias != alias.lower() or alias != " ".join(alias.split()):
            bad(f"alias {alias!r} must be non-empty, lowercase, single-spaced")
        if row["alias_locale"] not in CANONICAL_ALIAS_LOCALES:
            bad(f"alias_locale {row['alias_locale']!r} is not one of {', '.join(CANONICAL_ALIAS_LOCALES)}")
        if row["relationship"] not in CANONICAL_ALIAS_RELATIONSHIPS:
            bad(f"relationship {row['relationship']!r} is not one of {', '.join(CANONICAL_ALIAS_RELATIONSHIPS)}")
        if row["relationship"] in NOTE_REQUIRED and not row["alias_note"]:
            bad(f"a {row['relationship']} alias needs an alias_note for users")
        if row["ambiguous"] not in ("", "yes"):
            bad("ambiguous must be blank or 'yes'")
        pending = not row["reviewer"] or row["reviewer"].upper() == PENDING_REVIEWER
        reviewed = None
        if pending and require_signoff:
            bad("reviewer is missing: the row has not been signed off")
        if not pending or row["review_date"]:
            try:
                reviewed = date.fromisoformat(row["review_date"])
                if reviewed > today:
                    bad(f"review_date {row['review_date']} is in the future")
            except ValueError:
                bad(f"review_date {row['review_date']!r} must be an ISO date (YYYY-MM-DD)")

        alias_id = (row["alias_locale"], alias, key)
        if alias_id in seen_alias:
            bad(f"duplicate alias {alias!r} ({row['alias_locale']}) for {key}")
        seen_alias.add(alias_id)

        canonical = canonicals.get(key)
        fields = (concept, state, row["display_name_en_gb"], row["display_name_en_us"] or None, anchor)
        if canonical is None:
            canonical = CanonicalRow(key, *fields)
            canonicals[key] = canonical
        elif fields != (canonical.concept, canonical.preparation_state, canonical.display_name_en_gb,
                        canonical.display_name_en_us, canonical.anchor_fdc_id):
            bad(f"canonical columns differ from earlier rows of {key}")
        canonical.aliases.append(AliasRow(
            alias, row["alias_locale"], row["relationship"], row["alias_note"] or None,
            row["ambiguous"] == "yes", row["reviewer"], reviewed, line,
        ))

    problems.extend(_cross_row_problems(canonicals))
    if problems:
        raise CanonicalCsvError(problems)
    return canonicals


def _cross_row_problems(canonicals: dict[str, CanonicalRow]) -> list[str]:
    problems = []
    concepts_by_alias: dict[tuple[str, str], set[str]] = defaultdict(set)
    flagged: dict[tuple[str, str], bool] = defaultdict(lambda: True)
    for canonical in canonicals.values():
        for a in canonical.aliases:
            concepts_by_alias[(a.locale, a.alias)].add(canonical.concept)
            flagged[(a.locale, a.alias)] &= a.ambiguous
    for (locale, alias), concepts in sorted(concepts_by_alias.items()):
        # one alias for several preparation variants of a concept is normal
        # ("chickpeas"); for several concepts it must be marked ambiguous
        if len(concepts) > 1 and not flagged[(locale, alias)]:
            problems.append(
                f"alias {alias!r} ({locale}) points at concepts {sorted(concepts)}; mark every such row ambiguous=yes"
            )
    # Search reads a locale's own aliases and the '*' ones together, so the
    # same rule applies to their union ("chips": en-GB fries, en-US crisps
    # is fine; a '*' alias plus an en-GB one for another concept is not,
    # unless both say ambiguous).
    for (locale, alias), concepts in sorted(concepts_by_alias.items()):
        if locale == "*" or ("*", alias) not in concepts_by_alias:
            continue
        union = concepts | concepts_by_alias[("*", alias)]
        if len(union) > 1 and not (flagged[(locale, alias)] and flagged[("*", alias)]):
            problems.append(
                f"alias {alias!r} points at concepts {sorted(union)} across {locale} and '*'; "
                "mark every such row ambiguous=yes"
            )

    names = {c.concept for c in canonicals.values()} | set(canonicals)
    for canonical in canonicals.values():
        for a in canonical.aliases:
            if a.alias in names and a.alias not in (canonical.concept, canonical.key):
                problems.append(f"line {a.line}: alias {a.alias!r} is another concept's name or key")

    by_anchor: dict[int, list[str]] = defaultdict(list)
    for canonical in canonicals.values():
        by_anchor[canonical.anchor_fdc_id].append(canonical.key)
    for anchor, keys in sorted(by_anchor.items()):
        if anchor and len(keys) > 1:
            problems.append(f"anchor_fdc_id {anchor} is the anchor of more than one canonical: {sorted(keys)}")
    return problems


def load_file(path: Path = CSV_PATH, *, require_signoff: bool = True) -> dict[str, CanonicalRow]:
    return parse(path.read_text(encoding="utf-8"), require_signoff=require_signoff)
