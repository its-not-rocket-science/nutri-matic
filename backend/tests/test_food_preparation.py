"""Preparation-state classifier (canonical-foods plan PR 3).

The labelled fixture holds real public FDC names, generic and branded, each
with the state read from the name by a reviewer. The classifier must agree
with every row; a disagreement means either the rule or the label is wrong,
and the fix is reviewed like any other.
"""

import json
from pathlib import Path

import pytest

from app.food_preparation import (
    PREPARATION_STATES,
    UNCLASSIFIED_STATES,
    classify_preparation,
    preparation_label,
)
from app.preparation_coverage_report import render, summarise

LABELLED = json.loads((Path(__file__).parent / "fixtures" / "preparation_labelled.json").read_text(encoding="utf-8"))
_TYPES = {"G": None, "B": "branded_food"}


def test_labelled_fixture_is_well_formed():
    rows = LABELLED["rows"]
    assert len(rows) >= 100
    assert all(kind in _TYPES and state in PREPARATION_STATES for kind, _name, state in rows)
    # every state the vocabulary has, bar the rarely-named "soaked", is exercised
    assert {s for *_, s in rows} >= set(PREPARATION_STATES) - {"soaked"}
    assert any(kind == "B" for kind, *_ in rows)


@pytest.mark.parametrize("kind, name, state", LABELLED["rows"], ids=lambda v: str(v)[:50])
def test_classifier_matches_labelled_state(kind, name, state):
    assert classify_preparation(name, _TYPES[kind]) == state


def test_generic_rules_are_the_default_without_data_type():
    name = "Nuts, almonds, whole, raw"
    assert classify_preparation(name) == classify_preparation(name, "sr_legacy_food") == "raw"


def test_fresh_in_a_branded_name_is_not_a_state():
    """'Fresh' is mostly part of a brand ("Fresh Express"); generic FDC
    names use it as a state ("Parsley, fresh")."""
    assert classify_preparation("Parsley, fresh") == "raw"
    assert classify_preparation("Fresh Express Incorporated SPRING MIX", "branded_food") == "unspecified"


def test_component_cues_in_branded_composites_are_unknown_not_guessed():
    assert classify_preparation("HONEY ROASTED PEANUTS", "branded_food") == "roasted"
    assert classify_preparation("ICE CREAM WITH HONEY ROASTED PEANUTS", "branded_food") == "unknown"
    # the same text in a generic name keeps the FDC reading
    assert classify_preparation("Nuts, mixed nuts, dry roasted, with peanuts, salt added") == "roasted"


@pytest.mark.parametrize("name", ["", "   ", "X", "Cheese, cheddar", "CHEESE PIZZA"])
def test_names_without_a_cue_are_unspecified(name):
    assert classify_preparation(name) == "unspecified"
    assert classify_preparation(name, "branded_food") == "unspecified"


def test_unclassified_states_have_no_badge():
    assert set(UNCLASSIFIED_STATES) <= set(PREPARATION_STATES)
    for state in UNCLASSIFIED_STATES:
        assert preparation_label(state, "en-GB") is None
    for state in set(PREPARATION_STATES) - set(UNCLASSIFIED_STATES):
        assert preparation_label(state, "en-GB")


def test_coverage_summary_counts_by_type_and_lists_gaps():
    rows = [
        ("sr_legacy_food", "Lentils, raw"),
        ("sr_legacy_food", "Cheese, cheddar"),
        ("foundation_food", "Durian, raw or frozen"),
        ("branded_food", "13 FOODS CHICKPEAS"),
        ("branded_food", "BAYFRESH INC FROZEN WHITE SHRIMP"),
    ]
    summary = summarise(rows)
    assert summary["counts"]["sr_legacy_food"] == {"dry": 1, "unspecified": 1}
    assert summary["counts"]["branded_food"] == {"unspecified": 1, "frozen": 1}
    assert summary["unspecified_generic"] == ["Cheese, cheddar"]
    assert summary["unknown_generic"] == ["Durian, raw or frozen"]
    text = render(summary, sample=5)
    assert "| sr_legacy_food | 2 | 1 (50.0%) |" in text
    assert "- Durian, raw or frozen" in text
