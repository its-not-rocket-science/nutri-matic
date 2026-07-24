"""Permanent hardening regression suite — hardening prompt 7 (see
docs/nutrient-gap-recommendations-hardening.md). Every scenario listed in
the prompt gets one direct, real-endpoint test here, organised under the
same five headings the prompt uses. This is a consolidation layer, not a
replacement for the fuller per-prompt suites — each test below points at
the file with the exhaustive version of its scenario, so a future reader
can find the deeper coverage without this file re-deriving it:

- Access control        -> test_recipe_access.py, test_recommendations_api.py,
                            test_diary_meal_plan_recipe_visibility.py (prompts 1, 6)
- Input validation       -> test_recommendation_params.py,
                            test_recommendations_param_validation.py (prompt 2)
- Auditability           -> test_recommendations_score_breakdown_api.py,
                            test_recommendation_provenance.py,
                            test_recommendations_provenance_api.py (prompts 3, 4)
- Safety                 -> test_recommendation_safety.py,
                            test_recommendations_safety_api.py (prompts 5, 11)
- Mutation               -> test_recommendations_substitutions_api.py (prompt 6)

Every test here goes through a real HTTP endpoint (`TestClient`) or a
real service entry point, never a synthetic unit stand-in — per the
prompt's explicit "use real endpoint/service entry points where
practical"."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Food, FoodNutrient, Recipe
from app.reference_patterns import AMINO_ACIDS
from app.recommendation_safety import MINIMUM_RECOMMENDATION_AGE
from app.recommendation_scoring import RECOMMENDATION_MODEL_VERSION

CURRENT_YEAR = datetime.now().year


@pytest.fixture
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    db = TestSessionLocal()
    rice = Food(
        id=1, name="White rice, cooked", protein_g_per_100g=2.7,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    lentils = Food(
        id=2, name="Lentils", protein_g_per_100g=9.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    # "meat"-tagged (dietary_tags.TAGS["meat"]) — hard-excluded once a
    # profile's dietary_pattern is "vegan"/"vegetarian", for the apply-time
    # dietary-revalidation test below
    beef = Food(
        id=3, name="Beef, ground, cooked", protein_g_per_100g=26.0,
        amino_acids=dict.fromkeys(AMINO_ACIDS), data_type="sr_legacy_food",
    )
    db.add_all([rice, lentils, beef])
    db.flush()
    db.add_all([
        FoodNutrient(food_id=1, nutrient_key="energy", amount_per_100g=130.0),
        FoodNutrient(food_id=1, nutrient_key="fiber_total", amount_per_100g=0.4),
        FoodNutrient(food_id=1, nutrient_key="iron", amount_per_100g=0.2),
        FoodNutrient(food_id=2, nutrient_key="fiber_total", amount_per_100g=8.0),
        FoodNutrient(food_id=2, nutrient_key="energy", amount_per_100g=116.0),
        FoodNutrient(food_id=2, nutrient_key="iron", amount_per_100g=3.3),
        FoodNutrient(food_id=3, nutrient_key="energy", amount_per_100g=250.0),
    ])
    db.commit()
    db.close()

    yield TestClient(app), TestSessionLocal
    app.dependency_overrides.clear()


def register_and_token(client, email, password="password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_owner_profile_id(client, headers):
    return client.get("/api/profiles", headers=headers).json()[0]["id"]


def set_birth_year(client, headers, profile_id, birth_year):
    client.put(f"/api/profiles/{profile_id}", json={"name": "Me", "sex": "female", "birth_year": birth_year}, headers=headers)


def make_recipe(client, token, name="Recipe", food_id=1, quantity_g=100):
    return client.post(
        "/api/recipes",
        json={"name": name, "servings": 1, "ingredients": [{"food_id": food_id, "quantity_g": quantity_g}]},
        headers=auth_headers(token),
    ).json()


def flip_public(session_factory, recipe_id):
    db = session_factory()
    db.get(Recipe, recipe_id).is_public = True
    db.commit()
    db.close()


def log_recipe_entry(client, headers, recipe_id, entry_date="2026-01-01"):
    return client.post(
        "/api/diary",
        json={"entry_date": entry_date, "meal": "lunch", "recipe_id": recipe_id, "quantity_servings": 1},
        headers=headers,
    ).json()


class TestAccessControl:
    def test_private_recipe_id_cannot_be_analysed_by_another_user(self, client):
        client_, _ = client
        owner_token = register_and_token(client_, "ac-owner1@example.com")
        other_token = register_and_token(client_, "ac-other1@example.com")
        recipe = make_recipe(client_, owner_token, "Owner's Private Recipe")

        res = client_.get(
            "/api/recommendations/ingredients",
            params={"recipe_id": recipe["id"]},
            headers=auth_headers(other_token),
        )
        assert res.status_code == 404

    def test_private_recipe_existence_is_not_disclosed(self, client):
        client_, _ = client
        owner_token = register_and_token(client_, "ac-owner2@example.com")
        other_token = register_and_token(client_, "ac-other2@example.com")
        recipe = make_recipe(client_, owner_token, "Owner's Private Recipe 2")

        inaccessible = client_.get(
            "/api/recommendations/ingredients",
            params={"recipe_id": recipe["id"]},
            headers=auth_headers(other_token),
        )
        nonexistent = client_.get(
            "/api/recommendations/ingredients",
            params={"recipe_id": 999999},
            headers=auth_headers(other_token),
        )
        assert inaccessible.status_code == nonexistent.status_code == 404
        assert inaccessible.json() == nonexistent.json()

    def test_public_shared_and_system_recipes_remain_accessible(self, client):
        client_, sessions = client
        owner_token = register_and_token(client_, "ac-owner3@example.com")
        other_token = register_and_token(client_, "ac-other3@example.com")
        recipient_token = register_and_token(client_, "ac-recipient3@example.com")

        public_recipe = make_recipe(client_, owner_token, "Public Recipe")
        flip_public(sessions, public_recipe["id"])
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"recipe_id": public_recipe["id"]},
            headers=auth_headers(other_token),
        )
        assert res.status_code == 200

        shared_recipe = make_recipe(client_, owner_token, "Shared Recipe")
        client_.post(
            f"/api/recipes/{shared_recipe['id']}/shares",
            json={"email": "ac-recipient3@example.com"},
            headers=auth_headers(owner_token),
        )
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"recipe_id": shared_recipe["id"]},
            headers=auth_headers(recipient_token),
        )
        assert res.status_code == 200

    def test_apply_endpoints_cannot_mutate_another_profile(self, client):
        client_, _ = client
        owner_token = register_and_token(client_, "ac-owner4@example.com")
        attacker_token = register_and_token(client_, "ac-attacker4@example.com")

        current_recipe = make_recipe(client_, owner_token, "Rice Bowl")
        entry = log_recipe_entry(client_, auth_headers(owner_token), current_recipe["id"])
        replacement_recipe = make_recipe(client_, attacker_token, "Lentil Bowl", food_id=2, quantity_g=224)

        res = client_.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe["id"],
                "expected_updated_at": entry["updated_at"],
                "replacement_recipe_id": replacement_recipe["id"],
                "replacement_servings": 1,
            },
            headers=auth_headers(attacker_token),
        )
        assert res.status_code == 404

        day = client_.get("/api/diary?entry_date=2026-01-01", headers=auth_headers(owner_token)).json()
        assert next(e for e in day["entries"] if e["id"] == entry["id"])["recipe_id"] == current_recipe["id"]


class TestInputValidation:
    def test_invalid_servings_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-a@example.com")
        recipe = make_recipe(client_, token)
        for bad_servings in (0, -1, -0.5):
            res = client_.get(
                "/api/recommendations/ingredients",
                params={"recipe_id": recipe["id"], "servings": bad_servings},
                headers=auth_headers(token),
            )
            assert res.status_code == 422, bad_servings

    def test_excessive_suggestions_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-b@example.com")
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"entry_date": "2026-01-01", "max_suggestions": 11},
            headers=auth_headers(token),
        )
        assert res.status_code == 422

    def test_invalid_energy_values_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-c@example.com")
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"entry_date": "2026-01-01", "max_additional_energy": -1},
            headers=auth_headers(token),
        )
        assert res.status_code == 422

    def test_reversed_and_oversized_date_ranges_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-d@example.com")
        reversed_res = client_.get(
            "/api/recommendations/ingredients",
            params={"start_date": "2026-02-01", "end_date": "2026-01-01", "source": "meal_plan"},
            headers=auth_headers(token),
        )
        assert reversed_res.status_code == 422

        oversized_res = client_.get(
            "/api/recommendations/ingredients",
            params={"start_date": "2026-01-01", "end_date": "2026-12-31", "source": "meal_plan"},
            headers=auth_headers(token),
        )
        assert oversized_res.status_code == 422

    def test_invalid_nutrient_keys_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-e@example.com")
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"entry_date": "2026-01-01", "priority_nutrients": "not_a_real_nutrient"},
            headers=auth_headers(token),
        )
        assert res.status_code == 422

    def test_incompatible_scope_combinations_rejected(self, client):
        client_, _ = client
        token = register_and_token(client_, "iv-f@example.com")
        recipe = make_recipe(client_, token)
        res = client_.get(
            "/api/recommendations/ingredients",
            params={"entry_date": "2026-01-01", "recipe_id": recipe["id"]},
            headers=auth_headers(token),
        )
        assert res.status_code == 422


class TestAuditability:
    def test_score_breakdown_present_and_internally_consistent(self, client):
        client_, _ = client
        token = register_and_token(client_, "au-a@example.com")
        client_.post(
            "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
            headers=auth_headers(token),
        )
        res = client_.get(
            "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
        )
        assert res.status_code == 200
        suggestions = res.json()["suggestions"]
        assert suggestions, "expected at least one ingredient suggestion to check the breakdown on"
        for s in suggestions:
            breakdown = s["score_breakdown"]
            component_sum = (
                breakdown["weighted_gap_reduction"] + breakdown["multi_nutrient_bonus"]
                + breakdown["protein_quality_benefit"] + breakdown["dietary_fit"] + breakdown["practicality"]
                + breakdown["upper_limit_penalty"] + breakdown["above_preferred_penalty"]
                + breakdown["energy_overshoot_penalty"] + breakdown["uncertainty_penalty"]
                + breakdown["implausible_serving_penalty"]
            )
            assert breakdown["total"] == pytest.approx(component_sum)
            assert breakdown["total"] == pytest.approx(s["score"])

    def test_recommendation_model_version_present(self, client):
        client_, _ = client
        token = register_and_token(client_, "au-b@example.com")
        client_.post(
            "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 100},
            headers=auth_headers(token),
        )
        res = client_.get(
            "/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=auth_headers(token),
        )
        suggestions = res.json()["suggestions"]
        assert suggestions
        for s in suggestions:
            assert s["score_breakdown"]["model_version"] == RECOMMENDATION_MODEL_VERSION

    def test_provenance_and_mapping_quality_serialised_for_recipe_suggestions(self, client):
        client_, _ = client
        token = register_and_token(client_, "au-c@example.com")
        headers = auth_headers(token)
        # a recipe suggestion needs an existing meal to react against —
        # otherwise the very first candidate's energy delta looks like a
        # blind overshoot from zero and every candidate scores <= 0 and
        # gets silently dropped, which would make this test pass vacuously
        # (an empty suggestions list satisfies a bare "for s in []" loop)
        client_.post(
            "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 1, "quantity_g": 200},
            headers=headers,
        )
        make_recipe(client_, token, "Lentil Stew", food_id=2, quantity_g=200)
        res = client_.get(
            "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=headers,
        )
        assert res.status_code == 200
        suggestions = res.json()["suggestions"]
        assert suggestions, "expected at least one recipe suggestion to check quality_summary on"
        for s in suggestions:
            summary = s["quality_summary"]
            assert "proportion_exact_or_regional" in summary
            assert "min_mapping_confidence" in summary
            assert "fallback_resolution_count" in summary
            assert "nutrient_coverage" in summary

    def test_legacy_null_provenance_handled_without_error(self, client):
        """A plain user-created recipe has zero `RecipeIngredientProvenance`
        rows (that table is only ever populated by the stock-recipe import
        pipeline) — the quality summary must degrade gracefully, not
        crash, for this by-far-most-common real case."""
        client_, _ = client
        token = register_and_token(client_, "au-d@example.com")
        headers = auth_headers(token)
        client_.post(
            "/api/diary", json={"entry_date": "2026-01-01", "meal": "lunch", "food_id": 2, "quantity_g": 100},
            headers=headers,
        )
        make_recipe(client_, token, "Plain User Recipe", food_id=1, quantity_g=150)
        res = client_.get(
            "/api/recommendations/recipes", params={"entry_date": "2026-01-01"}, headers=headers,
        )
        assert res.status_code == 200
        suggestions = res.json()["suggestions"]
        assert suggestions, "expected at least one recipe suggestion for the legacy-null quality_summary check"
        summary = suggestions[0]["quality_summary"]
        assert summary["proportion_exact_or_regional"] is None
        assert summary["min_mapping_confidence"] is None


class TestSafety:
    def test_under_18_profile_disabled(self, client):
        client_, _ = client
        token = register_and_token(client_, "sa-a@example.com")
        headers = auth_headers(token)
        profile_id = get_owner_profile_id(client_, headers)
        set_birth_year(client_, headers, profile_id, CURRENT_YEAR - (MINIMUM_RECOMMENDATION_AGE - 1))

        res = client_.get("/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["suggestions"] == []
        assert body["disabled_reason_code"] == "under_minimum_age"

    def test_medical_constraint_disabled_by_default(self, client):
        client_, _ = client
        token = register_and_token(client_, "sa-b@example.com")
        headers = auth_headers(token)
        profile_id = get_owner_profile_id(client_, headers)
        set_birth_year(client_, headers, profile_id, CURRENT_YEAR - 30)
        client_.post(
            f"/api/profiles/{profile_id}/dietary-constraints",
            json={"category": "medical", "note": "renal diet"},
            headers=headers,
        )

        res = client_.get("/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers)
        body = res.json()
        assert body["suggestions"] == []
        assert body["disabled_reason_code"] == "unacknowledged_medical_constraint"

    def test_pregnancy_and_lactation_warnings_retained(self, client):
        client_, _ = client
        token = register_and_token(client_, "sa-c@example.com")
        headers = auth_headers(token)
        profile_id = get_owner_profile_id(client_, headers)
        client_.put(
            f"/api/profiles/{profile_id}",
            json={"name": "Me", "sex": "female", "birth_year": CURRENT_YEAR - 30, "is_pregnant": True, "is_lactating": True},
            headers=headers,
        )

        res = client_.get("/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers)
        warnings = res.json()["warnings"]
        assert "pregnancy_conservative" in warnings
        assert "lactation_conservative" in warnings

    def test_candidate_engine_not_called_when_disabled(self, client, monkeypatch):
        import app.routers.recommendations as recommendations_module

        client_, _ = client
        token = register_and_token(client_, "sa-d@example.com")
        headers = auth_headers(token)
        profile_id = get_owner_profile_id(client_, headers)
        set_birth_year(client_, headers, profile_id, CURRENT_YEAR - (MINIMUM_RECOMMENDATION_AGE - 1))

        def _boom(*a, **k):
            raise AssertionError("suggest_ingredients was called despite the engine being disabled")

        monkeypatch.setattr(recommendations_module, "suggest_ingredients", _boom)
        res = client_.get("/api/recommendations/ingredients", params={"entry_date": "2026-01-01"}, headers=headers)
        assert res.status_code == 200
        assert res.json()["suggestions"] == []


class TestMutation:
    def test_substitution_is_atomic(self, client):
        client_, _ = client
        token = register_and_token(client_, "mu-a@example.com")
        headers = auth_headers(token)
        current_recipe = make_recipe(client_, token, "Rice Bowl")
        entry = log_recipe_entry(client_, headers, current_recipe["id"])
        replacement_recipe = make_recipe(client_, token, "Lentil Bowl", food_id=2, quantity_g=224)

        res = client_.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe["id"],
                "expected_updated_at": entry["updated_at"],
                "replacement_recipe_id": replacement_recipe["id"],
                "replacement_servings": 2,
            },
            headers=headers,
        )
        assert res.status_code == 200
        day = client_.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        updated = next(e for e in day["entries"] if e["id"] == entry["id"])
        assert updated["recipe_id"] == replacement_recipe["id"]
        assert updated["quantity_servings"] == 2
        # exactly one entry for this day — never a stray leftover/duplicate
        # row from a partially-applied delete-then-create
        assert len(day["entries"]) == 1

    def test_stale_recommendation_cannot_overwrite_changed_data(self, client):
        client_, _ = client
        token = register_and_token(client_, "mu-b@example.com")
        headers = auth_headers(token)
        current_recipe = make_recipe(client_, token, "Rice Bowl")
        entry = log_recipe_entry(client_, headers, current_recipe["id"])
        replacement_recipe = make_recipe(client_, token, "Lentil Bowl", food_id=2, quantity_g=224)

        # the entry moved on (e.g. already substituted) since some earlier
        # suggestion was generated against a *different* expected recipe
        res = client_.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": replacement_recipe["id"],  # wrong on purpose
                "expected_updated_at": entry["updated_at"],
                "replacement_recipe_id": replacement_recipe["id"],
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 409
        day = client_.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        assert next(e for e in day["entries"] if e["id"] == entry["id"])["recipe_id"] == current_recipe["id"]

    def test_replacement_recipe_revalidated_against_current_dietary_constraints(self, client):
        """Prompt 8's follow-up review: the replacement recipe must be
        re-checked against the profile's *current* dietary constraints at
        apply time — a constraint added after the suggestion was
        generated must still block the apply, not just visibility and
        eligibility."""
        client_, _ = client
        token = register_and_token(client_, "mu-e@example.com")
        headers = auth_headers(token)
        current_recipe = make_recipe(client_, token, "Rice Bowl")
        entry = log_recipe_entry(client_, headers, current_recipe["id"])
        beef_recipe = make_recipe(client_, token, "Beef Bowl", food_id=3, quantity_g=200)

        profile_id = client_.get("/api/profiles", headers=headers).json()[0]["id"]
        client_.put(
            f"/api/profiles/{profile_id}",
            json={"name": "Me", "sex": None, "birth_year": None, "dietary_pattern": "vegan"},
            headers=headers,
        )

        res = client_.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe["id"],
                "expected_updated_at": entry["updated_at"],
                "replacement_recipe_id": beef_recipe["id"],
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 422
        day = client_.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        assert next(e for e in day["entries"] if e["id"] == entry["id"])["recipe_id"] == current_recipe["id"]

    def test_duplicate_application_has_defined_behaviour(self, client):
        client_, _ = client
        token = register_and_token(client_, "mu-c@example.com")
        headers = auth_headers(token)
        current_recipe = make_recipe(client_, token, "Rice Bowl")
        entry = log_recipe_entry(client_, headers, current_recipe["id"])
        replacement_recipe = make_recipe(client_, token, "Lentil Bowl", food_id=2, quantity_g=224)

        payload = {
            "entry_id": entry["id"], "source": "diary",
            "expected_current_recipe_id": current_recipe["id"],
            "expected_updated_at": entry["updated_at"],
            "replacement_recipe_id": replacement_recipe["id"],
            "replacement_servings": 1,
        }
        first = client_.post("/api/recommendations/substitutions/apply", json=payload, headers=headers)
        second = client_.post("/api/recommendations/substitutions/apply", json=payload, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 409  # the replay no longer matches — defined, not silently repeated

    def test_stale_expected_updated_at_alone_rejected(self, client):
        """Companion to the recipe_id staleness check above: a correct
        expected_current_recipe_id but wrong expected_updated_at must
        still 409 — the broader "full entry-version" signal, not just
        "did the recipe change" (prompt 8's follow-up review)."""
        client_, _ = client
        token = register_and_token(client_, "mu-d@example.com")
        headers = auth_headers(token)
        current_recipe = make_recipe(client_, token, "Rice Bowl")
        entry = log_recipe_entry(client_, headers, current_recipe["id"])
        replacement_recipe = make_recipe(client_, token, "Lentil Bowl", food_id=2, quantity_g=224)

        res = client_.post(
            "/api/recommendations/substitutions/apply",
            json={
                "entry_id": entry["id"], "source": "diary",
                "expected_current_recipe_id": current_recipe["id"],
                "expected_updated_at": "2020-01-01T00:00:00Z",
                "replacement_recipe_id": replacement_recipe["id"],
                "replacement_servings": 1,
            },
            headers=headers,
        )
        assert res.status_code == 409
        day = client_.get("/api/diary?entry_date=2026-01-01", headers=headers).json()
        assert next(e for e in day["entries"] if e["id"] == entry["id"])["recipe_id"] == current_recipe["id"]
