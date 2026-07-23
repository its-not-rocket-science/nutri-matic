"""Schema invariants for ingredient_aliases.py's ALIASES/REVIEWED_FALLBACKS
tables — prompt section 10: "ensure every approximation carries explicit
rationale and confidence" should be an enforced property, not just a
convention future entries are expected to follow by copying existing
style. These tests fail loudly the moment a new entry skips any of it,
which is the whole point: catch a sloppy addition at test time, not as a
silent gap a reviewer has to notice by eye."""

import pytest

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
    """Not a hard requirement of AliasTarget itself, but a food_id without
    the name seen at review time defeats validate_reviewed_mappings'
    rename-drift check (prompt section 2) — it could never tell "renamed"
    apart from "always had no recorded name"."""
    for key, target in ALL_TABLES[table_name].items():
        if target.food_id is not None:
            assert target.expected_food_name, (
                f"{table_name}[{key!r}] pins food_id={target.food_id} but has no expected_food_name"
            )
