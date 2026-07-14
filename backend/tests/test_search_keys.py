import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_filter_keys_includes_food_and_recipe_groups(client):
    res = client.get("/api/search/keys")
    assert res.status_code == 200
    body = res.json()
    assert "food" in body
    assert "recipe" in body
    assert len(body["food"]) > 0
    assert len(body["recipe"]) > 0


def test_filter_keys_labels_score_and_protein_specially(client):
    res = client.get("/api/search/keys")
    body = res.json()
    by_key = {k["key"]: k for k in body["food"]}
    assert by_key["diaas_score"] == {"key": "diaas_score", "label": "DIAAS score", "unit": "%"}
    assert by_key["pdcaas_score"] == {"key": "pdcaas_score", "label": "PDCAAS score", "unit": "%"}
    assert by_key["protein_g_per_100g"] == {"key": "protein_g_per_100g", "label": "Protein", "unit": "g"}


def test_filter_keys_resolves_nutrient_labels_from_nutrients_module(client):
    from app.nutrients import NUTRIENTS

    res = client.get("/api/search/keys")
    body = res.json()
    by_key = {k["key"]: k for k in body["food"]}
    assert by_key["iron"]["label"] == NUTRIENTS["iron"].name
    assert by_key["iron"]["unit"] == NUTRIENTS["iron"].unit


def test_filter_keys_sorted_by_label(client):
    res = client.get("/api/search/keys")
    labels = [k["label"] for k in res.json()["food"]]
    assert labels == sorted(labels)
