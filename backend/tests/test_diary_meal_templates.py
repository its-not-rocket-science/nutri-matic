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
    db.add(Food(id=1, name="oatmeal", protein_g_per_100g=13, amino_acids=dict.fromkeys(AMINO_ACIDS, 20)))
    db.add(Food(id=2, name="banana", protein_g_per_100g=1, amino_acids=dict.fromkeys(AMINO_ACIDS, 5)))
    db.commit()
    db.close()

    yield TestClient(app)
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_create_template_rejects_empty_meal(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_snapshot_captures_items_and_count(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 2, "quantity_g": 100},
        headers=auth_headers(token),
    )
    # different meal, should not be captured
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 1, "quantity_g": 50},
        headers=auth_headers(token),
    )

    res = client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    template = res.json()
    assert template["name"] == "Usual breakfast"
    assert template["item_count"] == 2

    detail = client.get(f"/api/diary-meal-templates/{template['id']}", headers=auth_headers(token)).json()
    names = {i["food_name"] for i in detail["items"]}
    assert names == {"oatmeal", "banana"}


def test_list_templates_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    )

    assert client.get("/api/diary-meal-templates", headers=auth_headers(other_token)).json() == []
    assert len(client.get("/api/diary-meal-templates", headers=auth_headers(token)).json()) == 1


def test_apply_template_creates_entries_for_target_date_and_meal(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 2, "quantity_g": 100},
        headers=auth_headers(token),
    )
    template = client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    ).json()

    res = client.post(
        f"/api/diary-meal-templates/{template['id']}/apply?entry_date=2026-07-20&meal=lunch",
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 2
    assert all(e["entry_date"] == "2026-07-20" and e["meal"] == "lunch" for e in created)

    day = client.get("/api/diary?entry_date=2026-07-20", headers=auth_headers(token)).json()
    assert len(day["entries"]) == 2


def test_delete_template_removes_it_and_its_items(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    template = client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    ).json()

    res = client.delete(f"/api/diary-meal-templates/{template['id']}", headers=auth_headers(token))
    assert res.status_code == 204
    assert client.get("/api/diary-meal-templates", headers=auth_headers(token)).json() == []
    assert client.get(f"/api/diary-meal-templates/{template['id']}", headers=auth_headers(token)).status_code == 404


def test_cannot_access_other_users_template(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 150},
        headers=auth_headers(token),
    )
    template = client.post(
        "/api/diary-meal-templates",
        json={"name": "Usual breakfast", "entry_date": "2026-07-13", "meal": "breakfast"},
        headers=auth_headers(token),
    ).json()

    assert client.get(f"/api/diary-meal-templates/{template['id']}", headers=auth_headers(other_token)).status_code == 404
    assert client.delete(f"/api/diary-meal-templates/{template['id']}", headers=auth_headers(other_token)).status_code == 404
    assert (
        client.post(
            f"/api/diary-meal-templates/{template['id']}/apply?entry_date=2026-07-20&meal=lunch",
            headers=auth_headers(other_token),
        ).status_code
        == 404
    )
