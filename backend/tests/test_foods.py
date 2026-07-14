import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient
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
    food = Food(
        id=1,
        name="chicken",
        protein_g_per_100g=25,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 20),
        digestibility_diaas_source="measured",
        digestibility_pdcaas=0.9,
        digestibility_pdcaas_source="estimated",
        fdc_id=123456,
        data_type="foundation_food",
        gtin_upc=None,
    )
    db.add(food)
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=2.0),
            FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=10.0),
        ]
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def test_provenance_traces_dataset_and_nutrient_numbers(client):
    res = client.get("/api/foods/1/provenance")
    assert res.status_code == 200
    body = res.json()
    assert body["fdc_id"] == 123456
    assert body["data_type"] == "foundation_food"
    assert body["dataset_label"] == "USDA FoodData Central — Foundation Foods"
    assert body["digestibility_diaas_source"] == "measured"
    assert body["digestibility_pdcaas_source"] == "estimated"

    by_key = {n["key"]: n for n in body["nutrients"]}
    assert by_key["iron"]["amount_per_100g"] == 2.0
    assert by_key["iron"]["fdc_nutrient_nbr"] == "303"
    assert by_key["iron"]["drv_confidence"] == "live_confirmed"
    assert by_key["calcium"]["drv_confidence"] == "live_confirmed"


def test_provenance_404_unknown_food(client):
    res = client.get("/api/foods/999/provenance")
    assert res.status_code == 404


def test_nutrients_endpoint_includes_drv_confidence(client):
    res = client.get("/api/foods/1/nutrients")
    assert res.status_code == 200
    by_key = {n["key"]: n for n in res.json()}
    assert by_key["iron"]["drv_confidence"] == "live_confirmed"


def test_nutrients_endpoint_includes_methodology_version(client):
    from app.methodology import DRV_METHODOLOGY_VERSION

    res = client.get("/api/foods/1/nutrients")
    assert res.status_code == 200
    for n in res.json():
        assert n["drv_methodology_version"] == DRV_METHODOLOGY_VERSION


def test_pdcaas_score_endpoint_includes_methodology_version(client):
    from app.methodology import SCORING_METHODOLOGY_VERSION

    res = client.get("/api/foods/1/score?method=pdcaas")
    assert res.status_code == 200
    assert res.json()["methodology_version"] == SCORING_METHODOLOGY_VERSION
