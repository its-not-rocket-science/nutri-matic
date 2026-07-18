"""Stable identifiers and near-duplicate detection (prompt section 12).

A recipe's identity for import-approved's idempotency is the manifest
slug (Recipe.import_slug) — deliberately not a hash of title/URL, since a
manual entry may have no source URL and titles aren't guaranteed unique.
The helpers here are for the separate, softer concern: flagging that two
*different* candidates (different slugs, possibly different sources) look
like the same real-world recipe, so a maintainer can decide — never
merged automatically, per section 12's "do not automatically merge
recipes solely because their titles are similar"."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

TITLE_SIMILARITY_THRESHOLD = 0.82


def normalise_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def ingredient_fingerprint(ingredient_lines: list[str]) -> str:
    """Order-independent hash of a raw ingredient list — used to compare
    two candidates' ingredient sets regardless of the order they were
    listed in, or a content_fingerprint (which is source-payload-specific
    and order-sensitive) between fetches of the same URL."""
    normalised = sorted(re.sub(r"\s+", " ", line.strip().lower()) for line in ingredient_lines)
    return hashlib.sha256("|".join(normalised).encode("utf-8")).hexdigest()


def find_near_duplicates(candidates: list[tuple[str, str]]) -> list[tuple[str, str, float]]:
    """`candidates` is a list of (slug, name) pairs. Returns (slug_a,
    slug_b, similarity) triples for any pair whose normalised titles are
    similar enough to be worth a maintainer's attention — flagged in the
    review file's duplicate_candidates field, never auto-resolved."""
    normalised = [(slug, normalise_title(name)) for slug, name in candidates]
    flagged: list[tuple[str, str, float]] = []
    for i in range(len(normalised)):
        for j in range(i + 1, len(normalised)):
            slug_a, title_a = normalised[i]
            slug_b, title_b = normalised[j]
            if not title_a or not title_b:
                continue
            similarity = SequenceMatcher(None, title_a, title_b).ratio()
            if similarity >= TITLE_SIMILARITY_THRESHOLD:
                flagged.append((slug_a, slug_b, round(similarity, 3)))
    return flagged
