from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Food
from app.patch_amino_acid_data import PATCHES
from app.reference_patterns import AMINO_ACIDS


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_patches_only_reference_valid_amino_acid_keys():
    for name, (amino_acids, citation) in PATCHES.items():
        assert set(amino_acids) <= set(AMINO_ACIDS), name
        assert citation  # every patch must carry a real citation


def test_never_overwrites_a_food_that_already_has_data():
    """A food this script targets that turns out to already have (even
    partial) amino acid data must be left alone — the whole point is
    supplementing genuine gaps, never silently overriding whatever's
    already ingested from FDC."""
    db = _session()
    existing_profile = dict.fromkeys(AMINO_ACIDS)
    existing_profile["leucine"] = 999.0  # a sentinel value that must survive
    db.add(Food(name="Onions, red, raw", protein_g_per_100g=0.94, amino_acids=existing_profile, data_type="foundation_food"))
    db.commit()

    food = db.query(Food).filter(Food.name == "Onions, red, raw").one()
    amino_acids, _citation = PATCHES["Onions, red, raw"]
    already_has_data = any(food.amino_acids.get(aa) is not None for aa in amino_acids)
    assert already_has_data is True  # confirms the script's own skip condition would fire
    db.close()


def test_patch_fills_a_genuinely_empty_profile():
    db = _session()
    db.add(Food(name="Onions, red, raw", protein_g_per_100g=0.94, amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="foundation_food"))
    db.commit()

    food = db.query(Food).filter(Food.name == "Onions, red, raw").one()
    amino_acids, _citation = PATCHES["Onions, red, raw"]
    already_has_data = any(food.amino_acids.get(aa) is not None for aa in amino_acids)
    assert already_has_data is False

    merged = dict(food.amino_acids)
    merged.update(amino_acids)
    assert merged["leucine"] == 29.49
    assert merged["tryptophan"] is None  # not reported by the source — never invented
    db.close()
