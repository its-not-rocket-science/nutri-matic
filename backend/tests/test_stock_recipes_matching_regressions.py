"""Permanent negative regression fixtures for food_matching.py — prompt
section 8: a table-driven suite checking both positive ("resolves to the
right food") and negative ("never resolves to the wrong food") matching
expectations together.

Each row reproduces, in miniature, a real wrong-match bug that was found
and fixed while running the stock-recipe pipeline against a live FDC
catalog (see ingredient_aliases.py's provenance notes for the full story of
each one). The negative assertion is the point: the risk being guarded
against isn't "matching stops working" (that would fail loudly elsewhere)
but "matching starts confidently returning the wrong food again" — e.g. if
a future edit to the alias table, _word_and_search's ranking, or the
canonical/fuzzy tiers reintroduces a substring/word overlap that lets a
wrong candidate back in. Keep these rows permanent even if the underlying
alias/data-tier logic is refactored (prompt section 10) — they describe
the *behaviour* that must survive, not the implementation.

`expected_food_name=None` rows (currently-unaliased singular "red pepper"/
"baking potato") assert only the negative: these are documented gaps
(no alias covers the singular form), not proven-correct positive matches
— resolving to nothing at all is an acceptable outcome, resolving to the
forbidden food is not.
"""

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import match_ingredient


@dataclass
class RegressionCase:
    ingredient_text: str
    foods: list[str]
    # lowercase substring that must never appear in the resolved food's name
    forbidden_substring: str
    # asserted exactly, when the case has a confidently correct answer;
    # None for a documented gap where "unresolved" is an acceptable outcome
    expected_food_name: str | None = None


CASES: list[RegressionCase] = [
    RegressionCase(
        "white wine",
        ["Wheat, hard, white", "Alcoholic beverage, wine, table, white"],
        forbidden_substring="wheat",
        expected_food_name="Alcoholic beverage, wine, table, white",
    ),
    RegressionCase(
        "olive oil",
        ["Oil, olive", "Mayonnaise, reduced fat, with olive oil"],
        forbidden_substring="mayonnaise",
        expected_food_name="Oil, olive",
    ),
    RegressionCase(
        "egg",
        ["Egg, whole, raw, fresh", "Eggnog"],
        forbidden_substring="eggnog",
        expected_food_name="Egg, whole, raw, fresh",
    ),
    RegressionCase(
        "eggs",
        ["Egg, whole, raw, fresh", "Eggs, Grade A, Large, egg yolk"],
        forbidden_substring="yolk",
        expected_food_name="Egg, whole, raw, fresh",
    ),
    RegressionCase(
        "granola",
        ["Cereals, granola, homemade", "Candies, chocolate coated granola bar"],
        forbidden_substring="bar",
        expected_food_name="Cereals, granola, homemade",
    ),
    RegressionCase(
        "mixed beans",
        ["Beans, kidney, all types, canned", "Vegetables, mixed, canned, drained solids"],
        forbidden_substring="vegetable",
        expected_food_name="Beans, kidney, all types, canned",
    ),
    RegressionCase(
        "red pepper",
        ["Peppers, sweet, red, raw", "Peppers, hot chili, red, raw"],
        forbidden_substring="chili",
        expected_food_name=None,  # documented gap: no alias covers the bare singular form
    ),
    RegressionCase(
        "baking potato",
        ["Potatoes, flesh and skin, raw", "Potatoes, raw, skin"],
        forbidden_substring="raw, skin",
        expected_food_name=None,  # documented gap: no alias covers the bare singular form
    ),
    RegressionCase(
        "split peas",
        [
            "Peas, split, mature seeds, cooked, boiled, without salt",
            "Split pea soup, canned, reduced sodium, prepared with water",
        ],
        forbidden_substring="soup",
        expected_food_name="Peas, split, mature seeds, cooked, boiled, without salt",
    ),
    RegressionCase(
        "green beans",
        ["Beans, snap, green, raw", "Babyfood, green beans, strained, junior"],
        forbidden_substring="babyfood",
        expected_food_name="Beans, snap, green, raw",
    ),
    RegressionCase(
        "crusty bread",
        ["Bread, french or vienna, toasted", "Bread, cheese"],
        forbidden_substring="cheese",
        expected_food_name="Bread, french or vienna, toasted",
    ),
    RegressionCase(
        "braising steak",
        ["Beef, chuck, raw", "Sauce, steak, tomato based"],
        forbidden_substring="sauce",
        expected_food_name="Beef, chuck, raw",
    ),
    RegressionCase(
        "sardines in tomato sauce",
        ["Sardine, pacific, canned in tomato sauce, drained solids", "Sauce, steak, tomato based"],
        forbidden_substring="steak",
        expected_food_name="Sardine, pacific, canned in tomato sauce, drained solids",
    ),
]


def _db_with(*names: str):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    for name in names:
        session.add(Food(
            name=name, protein_g_per_100g=1.0, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
        ))
    session.commit()
    return session


@pytest.mark.parametrize("case", CASES, ids=[c.ingredient_text for c in CASES])
def test_matching_regression(case: RegressionCase):
    db = _db_with(*case.foods)
    result = match_ingredient(db, case.ingredient_text)

    if result.food is not None:
        assert case.forbidden_substring not in result.food.name.lower(), (
            f"{case.ingredient_text!r} matched forbidden food {result.food.name!r}"
        )

    if case.expected_food_name is not None:
        assert result.food is not None, f"{case.ingredient_text!r} should have resolved to {case.expected_food_name!r}"
        assert result.food.name == case.expected_food_name
