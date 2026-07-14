import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import assign_digestibility
from app.database import Base
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(assign_digestibility, "SessionLocal", factory)
    return factory


def make_food(db, id_, name, **overrides):
    food = Food(id=id_, name=name, protein_g_per_100g=10, amino_acids=dict.fromkeys(AMINO_ACIDS, None), **overrides)
    db.add(food)
    return food


def test_backfills_measured_and_estimated_tiers(session_factory, monkeypatch):
    db = session_factory()
    make_food(db, 1, "Egg, whole, cooked, hard-boiled")  # measured DIAAS + measured PDCAAS
    make_food(db, 2, "Beef, ground, 85% lean, raw")  # category fallback only
    make_food(db, 3, "Water, tap")  # no rule matches either method
    db.commit()
    db.close()

    monkeypatch.setattr(sys, "argv", ["assign_digestibility"])
    assign_digestibility.main()

    db = session_factory()
    egg = db.get(Food, 1)
    assert egg.digestibility_diaas_source == "measured"
    assert egg.digestibility_diaas["leucine"] == 0.876
    assert egg.digestibility_pdcaas_source == "measured"
    assert egg.digestibility_pdcaas == 0.97

    beef = db.get(Food, 2)
    assert beef.digestibility_diaas_source == "estimated"
    assert beef.digestibility_pdcaas_source == "estimated"

    water = db.get(Food, 3)
    assert water.digestibility_diaas is None
    assert water.digestibility_pdcaas is None
    db.close()


def test_does_not_overwrite_existing_values_without_flag(session_factory, monkeypatch):
    db = session_factory()
    make_food(
        db,
        1,
        "Egg, whole, cooked",
        digestibility_pdcaas=0.5,
        digestibility_pdcaas_source="measured",
    )
    db.commit()
    db.close()

    monkeypatch.setattr(sys, "argv", ["assign_digestibility"])
    assign_digestibility.main()

    db = session_factory()
    egg = db.get(Food, 1)
    assert egg.digestibility_pdcaas == 0.5  # untouched — already set, --overwrite not passed
    assert egg.digestibility_diaas is not None  # was null, so it does get backfilled
    db.close()


def test_overwrite_flag_reapplies_rules_to_every_food(session_factory, monkeypatch):
    db = session_factory()
    make_food(
        db,
        1,
        "Egg, whole, cooked",
        digestibility_pdcaas=0.5,
        digestibility_pdcaas_source="measured",
    )
    db.commit()
    db.close()

    monkeypatch.setattr(sys, "argv", ["assign_digestibility", "--overwrite"])
    assign_digestibility.main()

    db = session_factory()
    egg = db.get(Food, 1)
    assert egg.digestibility_pdcaas == 0.97  # re-applied from the rule table
    db.close()


def test_dry_run_does_not_persist_changes(session_factory, monkeypatch):
    db = session_factory()
    make_food(db, 1, "Egg, whole, cooked")
    db.commit()
    db.close()

    monkeypatch.setattr(sys, "argv", ["assign_digestibility", "--dry-run"])
    assign_digestibility.main()

    db = session_factory()
    egg = db.get(Food, 1)
    assert egg.digestibility_pdcaas is None  # dry run never committed
    db.close()
