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


def test_trends_averages_over_logged_days_grouped_by_week(client):
    token = register_and_token(client, "a@example.com")
    # 2026-07-13 (Mon) and 2026-07-14 (Tue) are the same week; 2026-07-20 is the next week
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-14", "meal": "breakfast", "food_id": 1, "quantity_g": 300},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-20", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get(
        "/api/diary/trends?start_date=2026-07-13&end_date=2026-07-20&group_by=week", headers=auth_headers(token)
    )
    assert res.status_code == 200
    body = res.json()
    assert body["group_by"] == "week"
    assert len(body["buckets"]) == 2

    week1 = body["buckets"][0]
    assert week1["bucket_start"] == "2026-07-13"
    assert week1["bucket_end"] == "2026-07-19"
    assert week1["logged_days"] == 2
    iron = next(n for n in week1["nutrients"] if n["key"] == "iron")
    # (100g@2mg/100g=2mg) + (300g@2mg/100g=6mg) averaged over 2 logged days = 4mg
    assert iron["avg_amount"] == pytest.approx(4.0)

    week2 = body["buckets"][1]
    assert week2["logged_days"] == 1
    iron2 = next(n for n in week2["nutrients"] if n["key"] == "iron")
    assert iron2["avg_amount"] == pytest.approx(2.0)


def test_trends_scoped_to_date_range_and_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-01-01", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(other_token),
    )

    res = client.get(
        "/api/diary/trends?start_date=2026-07-01&end_date=2026-07-31&group_by=month", headers=auth_headers(token)
    )
    assert res.status_code == 200
    assert res.json()["buckets"] == []


def test_gap_suggestions_picks_worst_percent_drv_and_ranks_foods(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 2, "quantity_g": 100},
        headers=auth_headers(token),
    )

    # totals: calcium 21mg/700 = 3%, phosphorus 217mg/550 = 39.5%, iron 2.2mg/14.8 = 14.9%,
    # vitamin_c 50mg/40 = 125% — calcium is the worst (lowest %DRV) gap
    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-13", headers=auth_headers(token))
    assert res.status_code == 200
    body = res.json()
    assert body["nutrient_key"] == "calcium"
    assert len(body["foods"]) == 2
    # oj's 11mg/100g calcium beats beef's 10mg/100g
    assert body["foods"][0]["food_name"] == "Orange juice, raw"
    assert body["foods"][0]["amount_per_100g"] == 11.0
    assert body["foods"][1]["food_name"] == "Beef, ground, cooked"


def test_gap_suggestions_none_when_nothing_logged(client):
    token = register_and_token(client, "a@example.com")
    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-13", headers=auth_headers(token))
    assert res.status_code == 200
    assert res.json() is None


def test_gap_suggestions_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary/gap-suggestions?entry_date=2026-07-13", headers=auth_headers(other_token))
    assert res.json() is None


def test_quick_add_recent_orders_by_last_logged(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-01", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 2, "quantity_g": 250},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary/quick-add", headers=auth_headers(token))
    assert res.status_code == 200
    recent = res.json()["recent"]
    assert [i["food_name"] for i in recent] == ["Orange juice, raw", "Beef, ground, cooked"]
    assert recent[0]["quantity_g"] == 250
    assert recent[0]["last_logged"] == "2026-07-13"


def test_quick_add_frequent_orders_by_log_count(client):
    token = register_and_token(client, "a@example.com")
    for d in ["2026-07-01", "2026-07-02", "2026-07-03"]:
        client.post(
            "/api/diary",
            json={"entry_date": d, "meal": "breakfast", "food_id": 1, "quantity_g": 100},
            headers=auth_headers(token),
        )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 2, "quantity_g": 250},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary/quick-add", headers=auth_headers(token))
    frequent = res.json()["frequent"]
    assert frequent[0]["food_name"] == "Beef, ground, cooked"
    assert frequent[0]["log_count"] == 3
    assert frequent[1]["log_count"] == 1


def test_quick_add_uses_most_recent_quantity_as_representative(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-01", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-05", "meal": "breakfast", "food_id": 1, "quantity_g": 175},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary/quick-add", headers=auth_headers(token))
    item = res.json()["recent"][0]
    assert item["quantity_g"] == 175
    assert item["log_count"] == 2


def test_quick_add_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-01", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.get("/api/diary/quick-add", headers=auth_headers(other_token))
    assert res.json() == {"recent": [], "frequent": []}


def test_quick_add_skips_deleted_recipe(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "temp recipe", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-01", "meal": "breakfast", "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(token),
    )
    client.delete(f"/api/recipes/{recipe['id']}", headers=auth_headers(token))

    res = client.get("/api/diary/quick-add", headers=auth_headers(token))
    assert res.json() == {"recent": [], "frequent": []}


def test_copy_day_duplicates_all_meals(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "lunch", "food_id": 2, "quantity_g": 200},
        headers=auth_headers(token),
    )

    res = client.post(
        "/api/diary/copy-day?source_date=2026-07-13&target_date=2026-07-14", headers=auth_headers(token)
    )
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 2
    assert all(e["entry_date"] == "2026-07-14" for e in created)

    target_day = client.get("/api/diary?entry_date=2026-07-14", headers=auth_headers(token)).json()
    assert len(target_day["entries"]) == 2
    # source day untouched
    source_day = client.get("/api/diary?entry_date=2026-07-13", headers=auth_headers(token)).json()
    assert len(source_day["entries"]) == 2


def test_copy_day_is_additive_not_overwriting(client):
    token = register_and_token(client, "a@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-14", "meal": "dinner", "food_id": 2, "quantity_g": 50},
        headers=auth_headers(token),
    )

    client.post("/api/diary/copy-day?source_date=2026-07-13&target_date=2026-07-14", headers=auth_headers(token))

    target_day = client.get("/api/diary?entry_date=2026-07-14", headers=auth_headers(token)).json()
    meals = {e["meal"] for e in target_day["entries"]}
    assert meals == {"breakfast", "dinner"}  # the pre-existing dinner entry survived


def test_copy_day_skips_deleted_recipe(client):
    token = register_and_token(client, "a@example.com")
    recipe = client.post(
        "/api/recipes",
        json={"name": "temp recipe", "servings": 1, "ingredients": [{"food_id": 1, "quantity_g": 100}]},
        headers=auth_headers(token),
    ).json()
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "recipe_id": recipe["id"], "quantity_servings": 1},
        headers=auth_headers(token),
    )
    client.delete(f"/api/recipes/{recipe['id']}", headers=auth_headers(token))

    res = client.post(
        "/api/diary/copy-day?source_date=2026-07-13&target_date=2026-07-14", headers=auth_headers(token)
    )
    assert res.json() == []


def test_copy_day_scoped_to_user(client):
    token = register_and_token(client, "a@example.com")
    other_token = register_and_token(client, "b@example.com")
    client.post(
        "/api/diary",
        json={"entry_date": "2026-07-13", "meal": "breakfast", "food_id": 1, "quantity_g": 100},
        headers=auth_headers(token),
    )

    res = client.post(
        "/api/diary/copy-day?source_date=2026-07-13&target_date=2026-07-14", headers=auth_headers(other_token)
    )
    assert res.json() == []
