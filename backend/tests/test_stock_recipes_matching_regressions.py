"""Permanent negative regression fixtures for food_matching.py — prompt
section 3.

Each test below reproduces, in miniature, a real wrong-match bug that was
found and fixed while running the stock-recipe pipeline against a live FDC
catalog (see ingredient_aliases.py's provenance notes for the full story of
each one). These are deliberately negative assertions ("must NOT resolve to
X") rather than just checking the happy path: the risk they guard against
isn't "matching stops working" (that would fail loudly elsewhere) but
"matching starts confidently returning the wrong food again" — e.g. if a
future edit to the alias table, _word_and_search's ranking, or the
canonical/fuzzy tiers reintroduces a substring/word overlap that lets a
wrong candidate back in. Keep these fixtures permanent even if the
underlying alias/data-tier logic is refactored (prompt section 10) — they
describe the *behaviour* that must survive, not the implementation.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS
from app.stock_recipes.food_matching import match_ingredient


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


def test_white_wine_must_not_match_wheat():
    # was resolving to "Wheat, hard, white" purely on the shared word
    # "white" — crediting the recipe with wheat's protein instead of
    # wine's near-zero protein (see ingredient_aliases.py: "white wine")
    db = _db_with("Wheat, hard, white", "Alcoholic beverage, wine, table, white")
    result = match_ingredient(db, "white wine")
    assert result.food is not None
    assert "wheat" not in result.food.name.lower()
    assert result.food.name == "Alcoholic beverage, wine, table, white"


def test_olive_oil_must_not_match_mayonnaise():
    # was resolving to "Mayonnaise, reduced fat, with olive oil" ahead of
    # the actual "Oil, olive" entry, purely on alphabetical tiebreak
    db = _db_with("Oil, olive", "Mayonnaise, reduced fat, with olive oil")
    result = match_ingredient(db, "olive oil")
    assert result.food is not None
    assert "mayonnaise" not in result.food.name.lower()
    assert result.food.name == "Oil, olive"


def test_egg_must_not_match_eggnog():
    # bare "egg" was resolving to "Eggnog" — a serious category mismatch,
    # not just a missing-data problem
    db = _db_with("Egg, whole, raw, fresh", "Eggnog")
    result = match_ingredient(db, "egg")
    assert result.food is not None
    assert result.food.name != "Eggnog"
    assert result.food.name == "Egg, whole, raw, fresh"


def test_granola_must_not_match_granola_bar():
    # "granola" was resolving to a chocolate-coated granola BAR, not the
    # breakfast cereal a recipe means
    db = _db_with("Cereals, granola, homemade", "Candies, chocolate coated granola bar")
    result = match_ingredient(db, "granola")
    assert result.food is not None
    assert "bar" not in result.food.name.lower()
    assert result.food.name == "Cereals, granola, homemade"


def test_mixed_beans_must_not_match_mixed_vegetables():
    # the only "mixed"+"bean" hit in FDC is a mixed VEGETABLE medley
    # (corn/lima beans/peas/carrots) — a real category mismatch for a
    # recipe that means an actual tin of mixed beans
    db = _db_with("Beans, kidney, all types, canned", "Vegetables, mixed, canned, drained solids")
    result = match_ingredient(db, "mixed beans")
    assert result.food is not None
    assert "vegetable" not in result.food.name.lower()
    assert result.food.name == "Beans, kidney, all types, canned"


def test_red_pepper_must_not_match_chilli_pepper():
    # "red peppers" (plural) has a curated alias; bare singular "red
    # pepper" currently has none and falls through to canonical/fuzzy —
    # which, given FDC's comma-punctuated naming, doesn't resolve at all
    # here rather than confusing a sweet pepper for a hot chilli. Either
    # outcome (unresolved, or a correct future resolution) is acceptable;
    # silently landing on the chilli pepper is not.
    db = _db_with("Peppers, sweet, red, raw", "Peppers, hot chili, red, raw")
    result = match_ingredient(db, "red pepper")
    if result.food is not None:
        assert "chili" not in result.food.name.lower()


def test_baking_potato_must_not_match_potato_skin():
    # "baking potatoes" (plural) has a curated alias pointing at the
    # complete-data flesh-and-skin entry; bare singular "baking potato"
    # currently has none. Guard against it ever landing on the
    # no-amino-acid-data "Potatoes, raw, skin" entry the plural form used
    # to hit before its alias was added.
    db = _db_with("Potatoes, flesh and skin, raw", "Potatoes, raw, skin")
    result = match_ingredient(db, "baking potato")
    if result.food is not None:
        assert result.food.name != "Potatoes, raw, skin"


def test_split_peas_must_not_match_split_pea_soup():
    # bare "split peas" was resolving to a canned, prepared SOUP product
    # (no amino acid data), not the raw legume the recipe actually means
    db = _db_with(
        "Peas, split, mature seeds, cooked, boiled, without salt",
        "Split pea soup, canned, reduced sodium, prepared with water",
    )
    result = match_ingredient(db, "split peas")
    assert result.food is not None
    assert "soup" not in result.food.name.lower()
    assert result.food.name.startswith("Peas, split")
