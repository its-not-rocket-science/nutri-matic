import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import data_quality_audit
from app.data_quality_audit import main as audit_main, run_audit
from app.database import Base
from app.models import Food, FoodNutrient
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def seed_food(db, id_, name, data_type, **nutrients) -> None:
    food = Food(
        id=id_, name=name, data_type=data_type, protein_g_per_100g=5.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 5.0),
    )
    db.add(food)
    db.flush()
    for key, amount in nutrients.items():
        db.add(FoodNutrient(food_id=id_, nutrient_key=key, amount_per_100g=amount))


def test_ok_rows_are_never_included(db):
    seed_food(db, 1, "Ordinary food", "sr_legacy_food", biotin=10.0)
    db.commit()

    rows = run_audit(db)
    assert rows == []


def test_excluded_row_is_reported_with_disposition_and_source(db):
    seed_food(db, 1, "Branded outlier", "branded_food", biotin=29733.0)
    db.commit()

    rows = run_audit(db)
    assert len(rows) == 1
    assert rows[0].disposition == "excluded"
    assert rows[0].data_type == "branded_food"
    assert rows[0].nutrient_key == "biotin"
    assert rows[0].multiple > 900


def test_review_row_is_reported_but_distinguishable_from_excluded(db):
    seed_food(db, 1, "Liver, beef, cooked", "sr_legacy_food", biotin=1000.0)  # ~33x — review tier
    db.commit()

    rows = run_audit(db)
    assert len(rows) == 1
    assert rows[0].disposition == "review"


def test_disposition_filter_restricts_results(db):
    seed_food(db, 1, "Review-tier food", "sr_legacy_food", biotin=1000.0)
    seed_food(db, 2, "Excluded outlier", "branded_food", biotin=29733.0)
    db.commit()

    excluded_only = run_audit(db, dispositions={"excluded"})
    assert len(excluded_only) == 1
    assert excluded_only[0].disposition == "excluded"

    review_only = run_audit(db, dispositions={"review"})
    assert len(review_only) == 1
    assert review_only[0].disposition == "review"


def test_rows_sorted_highest_multiple_first(db):
    seed_food(db, 1, "Mild outlier", "sr_legacy_food", biotin=1000.0)
    seed_food(db, 2, "Severe outlier", "branded_food", biotin=29733.0)
    db.commit()

    rows = run_audit(db)
    assert [r.food_id for r in rows] == [2, 1]


def test_cli_prints_summary_and_rows(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(data_quality_audit, "SessionLocal", Session)

    seed_food(db, 1, "Branded outlier", "branded_food", biotin=29733.0)
    db.commit()

    audit_main([])
    out = capsys.readouterr().out
    assert "1 flagged row" in out
    assert "biotin" in out
    assert "branded_food" in out
    assert "excluded" in out


def test_cli_disposition_flag_restricts_output(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(data_quality_audit, "SessionLocal", Session)

    seed_food(db, 1, "Review-tier food", "sr_legacy_food", biotin=1000.0)
    seed_food(db, 2, "Excluded outlier", "branded_food", biotin=29733.0)
    db.commit()

    audit_main(["--disposition", "excluded"])
    out = capsys.readouterr().out
    assert "1 flagged row" in out
