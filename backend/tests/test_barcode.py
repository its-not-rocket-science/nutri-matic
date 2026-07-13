import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food
from app.reference_patterns import AMINO_ACIDS


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSession()
    db.add(
        Food(
            id=1,
            name="Acme Cereal Bar",
            protein_g_per_100g=8,
            amino_acids=dict.fromkeys(AMINO_ACIDS, None),
            data_type="branded_food",
            gtin_upc="012345678905",
        )
    )
    db.add(
        Food(
            id=2,
            name="chicken breast, raw",
            protein_g_per_100g=23,
            amino_acids=dict.fromkeys(AMINO_ACIDS, 20),
            data_type="foundation_food",
        )
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lookup_by_barcode_finds_food(client):
    res = client.get("/api/foods/barcode/012345678905")
    assert res.status_code == 200
    assert res.json()["name"] == "Acme Cereal Bar"


def test_lookup_unknown_barcode_404s(client):
    res = client.get("/api/foods/barcode/999999999999")
    assert res.status_code == 404


def test_food_without_barcode_has_null_gtin_upc(client):
    res = client.get("/api/foods/2")
    assert res.status_code == 200
    assert res.json()["gtin_upc"] is None
