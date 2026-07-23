"""Schema invariants for ingredient_aliases.py's ALIASES/REVIEWED_FALLBACKS
tables — prompt section 10: "ensure every approximation carries explicit
rationale and confidence" should be an enforced property, not just a
convention future entries are expected to follow by copying existing
style. These tests fail loudly the moment a new entry skips any of it,
which is the whole point: catch a sloppy addition at test time, not as a
silent gap a reviewer has to notice by eye."""

import ast
import inspect

import pytest

from app.stock_recipes import ingredient_aliases
from app.stock_recipes.ingredient_aliases import ALIASES, REVIEWED_FALLBACKS, AliasRelationship, AliasTarget

ALL_TABLES = {"ALIASES": ALIASES, "REVIEWED_FALLBACKS": REVIEWED_FALLBACKS}


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_every_entry_is_an_alias_target(table_name):
    for key, target in ALL_TABLES[table_name].items():
        assert isinstance(target, AliasTarget), f"{table_name}[{key!r}] is not an AliasTarget"


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_every_entry_has_a_non_empty_rationale(table_name):
    for key, target in ALL_TABLES[table_name].items():
        assert target.rationale and target.rationale.strip(), f"{table_name}[{key!r}] has no rationale"


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_every_entry_has_a_valid_relationship(table_name):
    for key, target in ALL_TABLES[table_name].items():
        assert isinstance(target.relationship, AliasRelationship), (
            f"{table_name}[{key!r}].relationship is not an AliasRelationship"
        )


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_every_entry_has_a_confidence_in_range(table_name):
    for key, target in ALL_TABLES[table_name].items():
        assert 0.0 < target.confidence <= 1.0, f"{table_name}[{key!r}].confidence={target.confidence!r} out of range"


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_every_entry_has_a_non_empty_search_phrase(table_name):
    for key, target in ALL_TABLES[table_name].items():
        assert target.search_phrase and target.search_phrase.strip(), f"{table_name}[{key!r}] has no search_phrase"


@pytest.mark.parametrize("table_name", ALL_TABLES)
def test_food_id_pinned_entries_also_record_expected_food_name(table_name):
    """Not a hard requirement of AliasTarget itself, but a food_id/fdc_id
    without the name seen at review time defeats validate_reviewed_
    mappings' rename-drift check (prompt sections 2/4) — it could never
    tell "renamed" apart from "always had no recorded name"."""
    for key, target in ALL_TABLES[table_name].items():
        if target.food_id is not None or target.fdc_id is not None:
            assert target.expected_food_name, (
                f"{table_name}[{key!r}] pins an id but has no expected_food_name"
            )


@pytest.mark.parametrize("table_name", ["ALIASES", "REVIEWED_FALLBACKS"])
def test_no_duplicate_keys_in_the_source_dict_literal(table_name):
    """A duplicate key in a Python dict literal is not a SyntaxError — the
    second occurrence silently overwrites the first, so `len(ALIASES)`
    alone can never catch it (prompt section 2: "add validation for
    duplicate keys"). Parse the actual source AST and check the literal's
    keys directly, which is the only way to see a collision that the
    runtime dict object itself already resolved away."""
    source = inspect.getsource(ingredient_aliases)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if target is not None and getattr(target, "id", None) == table_name:
            keys = [k.value for k in node.value.keys]
            seen: set[str] = set()
            dupes = [k for k in keys if k in seen or seen.add(k)]
            assert not dupes, f"{table_name} source literal has duplicate key(s): {dupes}"
            return
    pytest.fail(f"could not find a {table_name} assignment in ingredient_aliases.py's source")
