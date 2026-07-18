"""Loads the version-controlled target recipe list — seed_data/manifest.json
— the "what we want in the stock library" list, kept deliberately separate
from the fetched-page cache (which is ephemeral/gitignored) and from
seed_data/manual_recipes.json (the "what we've actually hand-authored"
content for manual-source entries).

Every recipe the stock library should eventually contain gets a manifest
entry, whether or not it's been sourced yet — `report` (see pipeline.py)
uses this to show what's still outstanding. Adding a new target recipe is
just adding a JSON object here; no code change needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SEED_DATA_DIR = Path(__file__).parent / "seed_data"
MANIFEST_PATH = SEED_DATA_DIR / "manifest.json"
MANUAL_RECIPES_PATH = SEED_DATA_DIR / "manual_recipes.json"

# Source kinds a manifest entry can specify:
#   "manual" — content comes from seed_data/manual_recipes.json (hand-authored,
#              no network). source_url (if set) is attribution-only — it is
#              never fetched, only shown to end users as a "view original"
#              link.
#   "fetch"  — content comes from a live source adapter (see sources/) at
#              source_url, via `fetch`. Requires source_name to pick the
#              adapter (see sources/__init__.py's ADAPTERS registry).
SourceKind = str


@dataclass(frozen=True)
class ManifestEntry:
    slug: str  # stable identifier — matches manual_recipes.json keys, and
    # is one input to dedup.py's stable recipe id for manual entries
    name: str
    collections: list[str]
    source: SourceKind
    source_name: str | None = None
    source_url: str | None = None
    # discovery query, for a future `discover` extension that searches a
    # source rather than being given an exact URL — unused by the two
    # adapters shipped today (both need a concrete URL/slug), kept as a
    # manifest field per prompt section 19 so it's there when needed.
    discovery_query: str | None = None
    dietary_characteristics: list[str] = field(default_factory=list)
    educational_note: str | None = None
    priority: int = 3  # 1 (highest) - 5 (lowest)
    notes: str | None = None

    @staticmethod
    def from_dict(d: dict) -> "ManifestEntry":
        return ManifestEntry(
            slug=d["slug"],
            name=d["name"],
            collections=list(d["collections"]),
            source=d["source"],
            source_name=d.get("source_name"),
            source_url=d.get("source_url"),
            discovery_query=d.get("discovery_query"),
            dietary_characteristics=list(d.get("dietary_characteristics", [])),
            educational_note=d.get("educational_note"),
            priority=d.get("priority", 3),
            notes=d.get("notes"),
        )


def load_manifest(path: Path = MANIFEST_PATH) -> list[ManifestEntry]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = [ManifestEntry.from_dict(d) for d in raw]
    slugs = [e.slug for e in entries]
    duplicates = {s for s in slugs if slugs.count(s) > 1}
    if duplicates:
        raise ValueError(f"Duplicate manifest slug(s): {sorted(duplicates)}")
    return entries


def load_manual_recipes(path: Path = MANUAL_RECIPES_PATH) -> dict[str, dict]:
    """slug -> {"servings": int, "ingredients": [raw ingredient line, ...],
    "method_note": str|None}. Missing file is treated as empty (a fresh
    checkout with no manual content yet is a valid, if unhelpful, state)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)
