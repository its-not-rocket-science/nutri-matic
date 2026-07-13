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
    beef = Food(id=1, name="Beef, ground, cooked", protein_g_per_100g=26, amino_acids=dict.fromkeys(AMINO_ACIDS, 20))
    oj = Food(id=2, name="Orange juice, raw", protein_g_per_100g=0.7, amino_acids=dict.fromkeys(AMINO_ACIDS, None))
    db.add_all([beef, oj])
    db.flush()
    db.add_all(
        [
            FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=2.0),
            FoodNutrient(food_id=1, nutrient_key="calcium", amount_per_100g=10.0),
            FoodNutrient(food_id=1, nutrient_key="phosphorus", amount_per_100g=200.0),
            FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=0.2),
            FoodNutrient(food_id=2, nutrient_key="vitamin_c", amount_per_100g=50.0),
            FoodNutrient(food_id=2, nutrient_key="calcium", amount_per_100g=11.0),
            FoodNutrient(food_id=2, nutrient_key="phosphorus", amount_per_100g=17.0),
        ]
    )
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_day_summary_includes_iron_bioavailability_and_calcium_phosphorus(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-20", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-20", "meal": "breakfast", "food_id": 2, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary?entry_date=2026-07-20", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()

    assert len(body["iron_bioavailability"]) == 1
    breakfast = body["iron_bioavailability"][0]
    assert breakfast["meal"] == "breakfast"
    # 100g beef @ 2mg/100g = 2mg total, 40% heme -> 0.8mg heme, 1.2mg non-heme (estimated)
    # 200g OJ @ 0.2mg/100g = 0.4mg, all non-heme (plant, not estimated)
    assert breakfast["heme_iron_mg"] == pytest.approx(0.8)
    assert breakfast["non_heme_iron_mg"] == pytest.approx(1.6)
    assert breakfast["vitamin_c_mg"] == pytest.approx(100.0)  # 200g @ 50mg/100g
    assert breakfast["non_heme_absorption_tier"] == "enhanced"
    assert breakfast["iron_split_source"] == "estimated"
    assert breakfast["absorbed_heme_mg"] == pytest.approx(0.2)  # 25% of 0.8

    cp = body["calcium_phosphorus"]
    assert cp is not None
    # calcium: 100g beef @10 + 200g OJ @11*2=22 -> 10+22=32; phosphorus: 200 + 34 = 234
    assert cp["calcium_mg"] == pytest.approx(32.0)
    assert cp["phosphorus_mg"] == pytest.approx(234.0)


def test_day_summary_omits_iron_bioavailability_for_meals_with_no_iron(client):
    token = register_and_token(client, "a@example.com")
    no_iron_food_id = client.post(
        "/api/foods",
        json={
            "name": "Water, plain",
            "protein_g_per_100g": 0,
            "amino_acids": dict.fromkeys(AMINO_ACIDS),
        },
    ).json()["id"]

    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-21", "meal": "snack", "food_id": no_iron_food_id, "quantity_g": 250},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary?entry_date=2026-07-21", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json()["iron_bioavailability"] == []
