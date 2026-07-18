"""The manual/seed-file adapter — prompt section 3's "manual or seed-file
adapter so curated recipes can be added without scraping". Reads
seed_data/manual_recipes.json (hand-authored ingredient lines, no network,
no source-page content of any kind), keyed by manifest slug.

manual_recipes.json shape:
    {
      "<slug>": {
        "servings": <number>,
        "ingredients": ["<raw ingredient line>", ...],
        "method_note": "<optional short factual note, never step-by-step method>"
      },
      ...
    }
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .base import RawRecipe, SourceUnavailable

if TYPE_CHECKING:
    from ..manifest import ManifestEntry

NAME = "manual"


class ManualSeedAdapter:
    name = NAME

    def __init__(self, manual_recipes: dict[str, dict]):
        self._data = manual_recipes

    def fetch(self, entry: "ManifestEntry", cache_dir: Path, force_refresh: bool = False) -> RawRecipe:
        data = self._data.get(entry.slug)
        if data is None:
            raise SourceUnavailable(
                f"no seed_data/manual_recipes.json entry for slug {entry.slug!r} yet — "
                "add one, or change this manifest entry's source to \"fetch\""
            )
        ingredients = data.get("ingredients") or []
        if not ingredients:
            raise SourceUnavailable(f"manual_recipes.json entry {entry.slug!r} has no ingredients")

        fingerprint_payload = json.dumps(
            {"name": entry.name, "servings": data.get("servings"), "ingredient_lines": ingredients},
            sort_keys=True,
        )
        return RawRecipe(
            name=entry.name,
            servings=data.get("servings"),
            ingredient_lines=list(ingredients),
            canonical_url=entry.source_url,
            source_licence=None,
            content_fingerprint=hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        )
