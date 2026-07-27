"""Public-launch hardening prompt 7, Part A: GET /api/recipes/public no
longer renders/fetches the entire stock-recipe catalogue at once.

Measured before this change, against a realistic 250-stock-recipe/8-
ingredient-each catalogue (production-scale — see docs/stock-recipes.md
and the manifest's own ~250 entries): the unpaginated endpoint issued
1502 SQL queries and returned a 272KB payload for a single request,
because `_recipe_out` loads a recipe's ingredients/foods/owner/ratings/
tags/provenance — none of which the catalogue listing page actually
renders (it shows only name, servings, and rating). The tests below
assert the load-bearing property directly: query count and payload
bounded by the page size requested, not by how large the catalogue is."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Food, Recipe, RecipeIngredient, RecipeRating, User
from app.reference_patterns import AMINO_ACIDS


class QueryCounter:
    """See tests/test_recommendation_performance.py's identical helper —
    counts real SQL statements sent to the engine for one `with` block."""

    def __init__(self, session):
        self.engine = session.get_bind()
        self.count = 0

    def _before_cursor_execute(self, *_args, **_kwargs):
        self.count += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._before_cursor_execute)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._before_cursor_execute)


def _make_client_with_catalogue(n_recipes: int, ingredients_per_recipe: int = 8):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    system_user = User(email="stock@system.local", password_hash=hash_password("unguessable"), is_system=True)
    real_user = User(email="viewer@example.com", password_hash=hash_password("password123"))
    db.add_all([system_user, real_user])
    db.flush()

    foods = [
        Food(name=f"Ingredient {i}", protein_g_per_100g=5.0, amino_acids=dict.fromkeys(AMINO_ACIDS))
        for i in range(min(ingredients_per_recipe, 20))
    ]
    db.add_all(foods)
    db.flush()

    for i in range(n_recipes):
        recipe = Recipe(user_id=system_user.id, name=f"Stock Recipe {i:04d}", servings=4, is_public=True)
        db.add(recipe)
        db.flush()
        for j in range(ingredients_per_recipe):
            db.add(RecipeIngredient(recipe_id=recipe.id, food_id=foods[j % len(foods)].id, quantity_g=100))
        if i % 3 == 0:
            db.add(RecipeRating(recipe_id=recipe.id, user_id=real_user.id, rating=4))
    db.commit()
    db.close()

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"email": "viewer@example.com", "password": "password123"})
    token = res.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    client._nutrimatic_session_factory = Session  # for QueryCounter in tests below
    return client


def test_public_recipes_default_response_shape():
    client = _make_client_with_catalogue(5)
    try:
        res = client.get("/api/recipes/public")
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"items", "total", "limit", "offset"}
        assert body["total"] == 5
        assert body["limit"] == 24
        assert body["offset"] == 0
        assert len(body["items"]) == 5
        # the summary must not carry ingredients/tags/owner_email — those
        # are exactly the fields that made the old endpoint expensive and
        # the catalogue listing page never renders them
        assert set(body["items"][0].keys()) == {
            "id", "name", "servings", "average_rating", "rating_count", "is_stock",
        }
        assert body["items"][0]["is_stock"] is True
    finally:
        app.dependency_overrides.clear()


def test_public_recipes_respects_limit_and_offset():
    client = _make_client_with_catalogue(30)
    try:
        first_page = client.get("/api/recipes/public?limit=10&offset=0").json()
        second_page = client.get("/api/recipes/public?limit=10&offset=10").json()
        assert len(first_page["items"]) == 10
        assert len(second_page["items"]) == 10
        assert first_page["total"] == 30
        assert second_page["total"] == 30
        first_ids = {r["id"] for r in first_page["items"]}
        second_ids = {r["id"] for r in second_page["items"]}
        assert first_ids.isdisjoint(second_ids)  # no duplicate rows across pages

        last_page = client.get("/api/recipes/public?limit=10&offset=25").json()
        assert len(last_page["items"]) == 5  # partial final page, not padded or truncated to 0
    finally:
        app.dependency_overrides.clear()


def test_public_recipes_ordering_is_stable_across_pages():
    """Recipe.name isn't unique — ordering by (name, id) is what keeps
    LIMIT/OFFSET pagination from reordering or skipping rows when two
    recipes share a name."""
    client = _make_client_with_catalogue(3)
    try:
        db = client._nutrimatic_session_factory()
        system_user = db.query(User).filter(User.is_system.is_(True)).one()
        dup1 = Recipe(user_id=system_user.id, name="Duplicate Name", servings=2, is_public=True)
        dup2 = Recipe(user_id=system_user.id, name="Duplicate Name", servings=2, is_public=True)
        db.add_all([dup1, dup2])
        db.commit()
        dup1_id, dup2_id = dup1.id, dup2.id
        db.close()

        all_items = []
        for offset in range(0, 5, 2):
            page = client.get(f"/api/recipes/public?limit=2&offset={offset}").json()
            all_items.extend(page["items"])
        ids_seen = [item["id"] for item in all_items]
        assert len(ids_seen) == len(set(ids_seen))  # no id appears twice across pages
        assert dup1_id in ids_seen
        assert dup2_id in ids_seen
    finally:
        app.dependency_overrides.clear()


def test_public_recipes_limit_is_validated():
    client = _make_client_with_catalogue(1)
    try:
        assert client.get("/api/recipes/public?limit=0").status_code == 422
        assert client.get("/api/recipes/public?limit=101").status_code == 422
        assert client.get("/api/recipes/public?offset=-1").status_code == 422
        assert client.get("/api/recipes/public?limit=100").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_public_recipes_rating_aggregate_is_correct():
    client = _make_client_with_catalogue(3)
    try:
        body = client.get("/api/recipes/public?limit=3").json()
        rated = [r for r in body["items"] if r["rating_count"] > 0]
        unrated = [r for r in body["items"] if r["rating_count"] == 0]
        assert len(rated) == 1  # only recipe index 0 (i % 3 == 0) was rated
        assert rated[0]["average_rating"] == 4.0
        assert all(r["average_rating"] is None for r in unrated)
    finally:
        app.dependency_overrides.clear()


def test_public_recipes_excludes_the_callers_own_public_recipe():
    """Unchanged behaviour from the prior unpaginated version's `not
    r.is_owner` client-side filter — a caller's own public recipe (should
    a future community-share feature ever set is_public on a non-stock
    recipe) belongs in "My recipes", not repeated in this catalogue."""
    client = _make_client_with_catalogue(2)
    try:
        db = client._nutrimatic_session_factory()
        viewer = db.query(User).filter(User.email == "viewer@example.com").one()
        own_public_recipe = Recipe(user_id=viewer.id, name="My Own Public Recipe", servings=1, is_public=True)
        db.add(own_public_recipe)
        db.commit()
        own_recipe_id = own_public_recipe.id
        db.close()

        body = client.get("/api/recipes/public?limit=10").json()
        ids = {r["id"] for r in body["items"]}
        assert own_recipe_id not in ids
        assert body["total"] == 2  # the caller's own public recipe isn't counted either
    finally:
        app.dependency_overrides.clear()


def test_query_count_does_not_scale_with_catalogue_size():
    counts = {}
    for n in (20, 250):
        client = _make_client_with_catalogue(n)
        try:
            with QueryCounter(client._nutrimatic_session_factory()) as counter:
                res = client.get("/api/recipes/public?limit=24")
            assert res.status_code == 200
        finally:
            app.dependency_overrides.clear()
        counts[n] = counter.count

    # a >10x larger catalogue must not meaningfully change the query
    # count for one page — bounded by page size, not catalogue size
    assert counts[250] <= counts[20] + 2


def test_query_count_and_payload_are_bounded_by_page_size_not_catalogue_size():
    """The concrete regression this prompt fixes: the old endpoint issued
    ~6 queries per recipe (1502 for 250 recipes) and returned every
    recipe's full ingredient list (272KB) in one response, regardless of
    what the page actually needed to show."""
    client = _make_client_with_catalogue(250)
    try:
        with QueryCounter(client._nutrimatic_session_factory()) as counter:
            res = client.get("/api/recipes/public?limit=24")
        assert res.status_code == 200
        assert res.json()["total"] == 250
        assert len(res.json()["items"]) == 24
        # bounded (a handful of batched queries), nowhere near the ~1502
        # the unpaginated, per-recipe-hydrating version issued
        assert counter.count < 20
        assert len(res.content) < 20_000  # nowhere near the old 272KB
    finally:
        app.dependency_overrides.clear()
