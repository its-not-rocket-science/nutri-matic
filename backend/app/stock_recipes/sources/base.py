"""Shared shape every source adapter (manual, schema.org/JSON-LD, and any
future one) fetches into — deliberately narrow: only what's needed for
ingredient-level nutrition analysis, per prompt section 3. Cooking method,
photos, editorial prose, and comments are never part of this shape, so
there's no code path that could accidentally store them even if a source's
raw payload contains them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from ..manifest import ManifestEntry


@dataclass
class RawRecipe:
    name: str
    servings: float | None
    ingredient_lines: list[str]
    canonical_url: str | None
    source_licence: str | None
    # sha256 of the extracted {name, servings, ingredient_lines} — used by
    # pipeline.py to detect when a source recipe's actual content changed
    # between fetches (Recipe.content_fingerprint), independent of
    # incidental page markup/formatting changes.
    content_fingerprint: str
    # the URL actually reached after following any redirects, when this
    # fetch made a live HTTP request — None when nothing was fetched live
    # (a cache hit, or a source with no HTTP concept at all, e.g. the
    # manual adapter). Lets health_check.py (prompt section 5) tell a
    # source-side redirect apart from "no redirect happened"; not used for
    # anything else (canonical_url, not this, is what gets stored/compared
    # as the recipe's source_url).
    resolved_url: str | None = None


class SourceUnavailable(Exception):
    """Raised by an adapter's fetch() for anything that means "this
    candidate can't be sourced right now" — disallowed by robots.txt, the
    page 404s/redirects away, no schema.org Recipe found, a request that
    still failed after retrying. Always carries a human-readable reason;
    pipeline.py records it verbatim as the candidate's stock_status
    "source_unavailable" reason rather than a raw exception traceback."""


class SourceAdapter(Protocol):
    name: str

    def fetch(self, entry: "ManifestEntry", cache_dir: "Path", force_refresh: bool = False) -> RawRecipe: ...
