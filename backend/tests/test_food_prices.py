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
    db.add(Food(id=1, name="chicken", protein_g_per_100g=25, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.add(Food(id=2, name="rice", protein_g_per_100g=7, amino_acids=dict.fromkeys(AMINO_ACIDS, 5)))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_set_price_computes_per_100g(client):
    token = register_and_token(client, "a@example.com")
    res = client.put(
        "/api/food-prices/1", json={"package_price": 5.0, "package_quantity_g": 500}, headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["price_per_100g"] == pytest.approx(1.0)
    assert body["food_name"] == "chicken"


def test_update_existing_price_overwrites(client):
    token = register_and_token(client, "a@example.com")
    client.put("/api/food-prices/1", json={"package_price": 5.0, "package_quantity_g": 500}, headers=auth_headers(token))
    res = client.put(
        "/api/food-prices/1", json={"package_price": 4.0, "package_quantity_g": 400}, headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json()["price_per_100g"] == pytest.approx(1.0)

    listed = client.get("/api/food-prices", headers=auth_headers(token)).json()
    assert len(listed) == 1


def test_set_price_unknown_food_422(client):
    token = register_and_token(client, "a@example.com")
    res = client.put(
        "/api/food-prices/999", json={"package_price": 5.0, "package_quantity_g": 500}, headers=auth_headers(token)
    )
    assert res.status_code == 422


def test_prices_scoped_per_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.put("/api/food-prices/1", json={"package_price": 5.0, "package_quantity_g": 500}, headers=auth_headers(token))

    other_prices = client.get("/api/food-prices", headers=auth_headers(other_token)).json()
    assert other_prices == []


def test_delete_price(client):
    token = register_and_token(client, "a@example.com")
    client.put("/api/food-prices/1", json={"package_price": 5.0, "package_quantity_g": 500}, headers=auth_headers(token))

    res = client.delete("/api/food-prices/1", headers=auth_headers(token))
    assert res.status_code == 204

    listed = client.get("/api/food-prices", headers=auth_headers(token)).json()
    assert listed == []


def test_delete_nonexistent_price_404s(client):
    token = register_and_token(client, "a@example.com")
    res = client.delete("/api/food-prices/1", headers=auth_headers(token))
    assert res.status_code == 404


def test_shopping_list_includes_budget(client):
    token = register_and_token(client, "a@example.com")
    client.put("/api/food-prices/1", json={"package_price": 6.0, "package_quantity_g": 600}, headers=auth_headers(token))
    # rice has no price set

    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-20", "meal": "lunch", "food_id": 1, "quantity_g": 300},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-20", "meal": "dinner", "food_id": 2, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/meal-plan/shopping-list?start_date=2026-07-18&end_date=2026-07-24", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["items_missing_price"] == 1
    assert body["total_cost"] == pytest.approx(3.0)  # 300g chicken @ $1/100g = $3, rice excluded

    items = {i["food_name"]: i for i in body["items"]}
    assert items["chicken"]["price_per_100g"] == pytest.approx(1.0)
    assert items["chicken"]["estimated_cost"] == pytest.approx(3.0)
    assert items["rice"]["price_per_100g"] is None
    assert items["rice"]["estimated_cost"] is None
