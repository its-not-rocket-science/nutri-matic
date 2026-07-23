"""Tests for seed_manual_foods.py's composite-food builder — prompt
section 7. Verifies the muesli composite (and the general mechanism) is
computed by weighting real component foods, using this app's own
aggregate_nutrients/aggregate_amino_acids, rather than fabricated figures."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS
from app.seed_manual_foods import COMPOSITE_FOODS, CompositeComponent, CompositeFoodSpec, _build_composite, _find_component


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _food(name, protein, aa_value, data_type="sr_legacy_food"):
    return Food(
        name=name, protein_g_per_100g=protein, amino_acids=dict.fromkeys(AMINO_ACIDS, aa_value), data_type=data_type,
    )


def test_find_component_prefers_complete_amino_acid_profile(db):
    incomplete = _food("Oats, whole grain, rolled, old fashioned", protein=13.0, aa_value=None)
    complete = _food("Oats", protein=13.0, aa_value=400.0)
    db.add_all([incomplete, complete])
    db.commit()

    found = _find_component(db, "oats")
    assert found.name == "Oats"


def test_find_component_returns_none_when_nothing_matches(db):
    assert _find_component(db, "nonexistent ingredient words") is None


def test_build_composite_weights_protein_and_amino_acids_by_mass_fraction(db):
    # two components, 50/50 by mass, distinct protein/amino-acid values —
    # the composite's protein must be the mass-weighted average, and its
    # amino acids the protein-weighted average (aggregate_amino_acids'
    # usual rule, exercised here on a purpose-built composite instead of
    # a recipe)
    oats = _food("Oats", protein=10.0, aa_value=100.0)
    raisins = _food("Raisins, seedless", protein=2.0, aa_value=50.0)
    db.add_all([oats, raisins])
    db.flush()
    db.add(FoodNutrient(food_id=oats.id, nutrient_key="energy", amount_per_100g=380))
    db.add(FoodNutrient(food_id=raisins.id, nutrient_key="energy", amount_per_100g=300))
    db.commit()

    spec = CompositeFoodSpec(
        name="Test Composite",
        components=[CompositeComponent("oats", 0.5), CompositeComponent("raisins seedless", 0.5)],
        rationale="test",
    )
    food, nutrients = _build_composite(db, spec)

    # protein: 50g oats (5.0g protein) + 50g raisins (1.0g protein) = 6.0g protein per 100g
    assert food.protein_g_per_100g == pytest.approx(6.0)
    # amino acids are protein-weighted: (5.0*100 + 1.0*50) / 6.0 = 91.67
    for aa in AMINO_ACIDS:
        assert food.amino_acids[aa] == pytest.approx((5.0 * 100 + 1.0 * 50) / 6.0)

    energy = next(n for n in nutrients if n.nutrient_key == "energy")
    # energy: 50g @ 380/100g + 50g @ 300/100g = 190 + 150 = 340
    assert energy.amount_per_100g == pytest.approx(340.0)


def test_build_composite_returns_none_when_a_component_is_missing(db):
    db.add(_food("Oats", protein=10.0, aa_value=100.0))
    db.commit()
    spec = CompositeFoodSpec(
        name="Test Composite",
        components=[CompositeComponent("oats", 0.5), CompositeComponent("raisins seedless", 0.5)],
        rationale="test",
    )
    assert _build_composite(db, spec) is None


def test_muesli_composite_spec_components_sum_to_one():
    muesli = next(spec for spec in COMPOSITE_FOODS if "Muesli" in spec.name)
    total = sum(c.mass_fraction for c in muesli.components)
    assert total == pytest.approx(1.0)
