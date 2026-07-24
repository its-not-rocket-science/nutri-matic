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


def test_create_template_rejects_non_week_range(client):
    token = register_and_token(client, "a@example.com")
    res = client.post(
        "/api/meal-plan-templates",
        json={"name": "My week", "start_date": "2026-07-13", "end_date": "2026-07-15"},
        headers=auth_headers(token),
    )
    assert res.status_code == 422


def test_snapshot_captures_day_offset_and_entry_count(client):
    token = register_and_token(client, "a@example.com")
    # Monday 2026-07-13 (offset 0), Wednesday 2026-07-15 (offset 2)
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-15", "meal": "dinner", "food_id": 2, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.post(
        "/api/meal-plan-templates",
        json={"name": "Typical week", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    template = res.json()
    assert template["name"] == "Typical week"
    assert template["entry_count"] == 2

    detail = client.get(f"/api/meal-plan-templates/{template['id']}", headers=auth_headers(token)).json()
    offsets = {e["day_offset"]: e["food_name"] for e in detail["entries"]}
    assert offsets == {0: "chicken", 2: "rice"}


def test_list_templates_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/meal-plan-templates",
        json={"name": "Week A", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(token),
    )

    other_list = client.get("/api/meal-plan-templates", headers=auth_headers(other_token)).json()
    assert other_list == []
    mine = client.get("/api/meal-plan-templates", headers=auth_headers(token)).json()
    assert len(mine) == 1


def test_apply_template_creates_entries_offset_from_start_date(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-15", "meal": "dinner", "food_id": 2, "quantity_g": 200},
        headers=auth_headers(token),
    )
    template = client.post(
        "/api/meal-plan-templates",
        json={"name": "Typical week", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(token),
    ).json()

    # apply to the following week, starting Monday 2026-07-20
    res = client.post(
        f"/api/meal-plan-templates/{template['id']}/apply?start_date=2026-07-20", headers=auth_headers(token)
    )
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 2
    dates = {e["plan_date"] for e in created}
    assert dates == {"2026-07-20", "2026-07-22"}  # offsets 0 and 2 from 2026-07-20

    week2 = client.get(
        "/api/meal-plan?start_date=2026-07-20&end_date=2026-07-26", headers=auth_headers(token)
    ).json()
    assert len(week2) == 2


def test_delete_template_removes_it_and_its_entries(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    template = client.post(
        "/api/meal-plan-templates",
        json={"name": "Typical week", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(token),
    ).json()

    res = client.delete(f"/api/meal-plan-templates/{template['id']}", headers=auth_headers(token))
    assert res.status_code == 204

    listed = client.get("/api/meal-plan-templates", headers=auth_headers(token)).json()
    assert listed == []

    res = client.get(f"/api/meal-plan-templates/{template['id']}", headers=auth_headers(token))
    assert res.status_code == 404


def test_cannot_access_other_users_template(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    template = client.post(
        "/api/meal-plan-templates",
        json={"name": "Typical week", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(token),
    ).json()

    assert client.get(f"/api/meal-plan-templates/{template['id']}", headers=auth_headers(other_token)).status_code == 404
    assert client.delete(f"/api/meal-plan-templates/{template['id']}", headers=auth_headers(other_token)).status_code == 404
    assert (
        client.post(
            f"/api/meal-plan-templates/{template['id']}/apply?start_date=2026-07-20", headers=auth_headers(other_token)
        ).status_code
        == 404
    )


def test_apply_template_keeps_a_shared_not_owned_recipe(client):
    """Same bug class hardening prompt 6 fixed in diary.py/meal_plan.py's
    own create paths (found during the prompt 8 follow-up review):
    apply_template used to check `recipe.user_id == current_user.id`
    (outright ownership), which silently dropped any template entry
    whose recipe the applying user could see but didn't own — e.g. one
    shared with them, exactly the case here."""
    owner_token = register_and_token(client, "owner@example.com")
    recipient_token = register_and_token(client, "recipient@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "Owner's Recipe", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(owner_token),
    ).json()
    client.post(
        f"/api/recipes/{recipe['id']}/shares",
        json={"email": "recipient@example.com"},
        headers=auth_headers(owner_token),
    )
    client.post(
        "/api/meal-plan",
        json={"plan_date": "2026-07-13", "meal": "breakfast", "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(recipient_token),
    )
    template = client.post(
        "/api/meal-plan-templates",
        json={"name": "Shared week", "start_date": "2026-07-13", "end_date": "2026-07-19"},
        headers=auth_headers(recipient_token),
    ).json()

    res = client.post(
        f"/api/meal-plan-templates/{template['id']}/apply?start_date=2026-07-20",
        headers=auth_headers(recipient_token),
    )
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 1
    assert created[0]["recipe_id"] == recipe["id"]
