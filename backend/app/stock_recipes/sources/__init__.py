"""Pluggable source adapters. A manifest entry's `source_name` (for
source="fetch" entries) selects one of these by NAME; source="manual"
entries always use ManualSeedAdapter regardless of source_name.

Adding a new live source is: write a class implementing SourceAdapter's
fetch() (see sources/schema_org.py for the reference implementation — most
new schema.org-JSON-LD sites need zero new code, just a manifest entry
with source_name="schema_org"), register it in build_adapters() below, and
document it in docs/stock-recipes.md's "supported sources" list.
"""

from __future__ import annotations

from .base import RawRecipe, SourceAdapter, SourceUnavailable
from .manual import ManualSeedAdapter
from .schema_org import SchemaOrgJsonLdAdapter

__all__ = [
    "RawRecipe",
    "SourceAdapter",
    "SourceUnavailable",
    "ManualSeedAdapter",
    "SchemaOrgJsonLdAdapter",
    "build_adapters",
]


def build_adapters(manual_recipes: dict[str, dict]) -> dict[str, SourceAdapter]:
    return {
        "manual": ManualSeedAdapter(manual_recipes),
        "schema_org": SchemaOrgJsonLdAdapter(),
    }
