"""Computes which of collections_config.py's "dietary" collections a
recipe qualifies for, from its actual resolved ingredients — prompt
section 11: "For nutritional collections, calculate membership from actual
Nutri-Matic analysis where appropriate" and "must preserve the
distinctions among allowed/discouraged/excluded/unknown."

Reuses the app's existing dietary_tags.evaluate_food exactly as the rest
of the app does (dietary_filter.py) — no separate suitability logic
invented for the stock library. A recipe only qualifies for a dietary
collection if EVERY resolved ingredient evaluates "ok" for that
pattern/tag combination; a single "unknown" (typically a low-confidence
branded-food name match) or "avoid"/"excluded" keeps it out. Unmatched
ingredients (never resolved to a Food at all) are treated the same as
"unknown" — an ingredient this pipeline couldn't even identify obviously
can't be verified suitable either, so it must not count as safe.
"""

from __future__ import annotations

from ..dietary_tags import evaluate_food
from ..models import Food
from .collections_config import COLLECTIONS


def compute_suitability_collections(foods: list[Food], has_unresolved_ingredients: bool = False) -> list[str]:
    if has_unresolved_ingredients:
        # can't verify what we don't know — an unmatched ingredient could
        # be anything, so no dietary claim is safe to make
        return []

    qualifying: list[str] = []
    for spec in COLLECTIONS.values():
        if spec.kind != "dietary":
            continue
        if all(
            evaluate_food(food.name, food.data_type, spec.dietary_pattern, list(spec.constraint_tags)).status == "ok"
            for food in foods
        ):
            qualifying.append(spec.key)
    return qualifying
