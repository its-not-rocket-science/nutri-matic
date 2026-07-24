"""Tests for recipe_access.py — the canonical recipe-visibility resolver
(hardening prompt 1). Covers every access class the resolver must
distinguish: owner, shared-with, public, system/stock, inaccessible
private, and nonexistent — all inaccessible cases returning the same
plain 404, never 403, so existence can't be inferred from status code."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Recipe, RecipeShare, User
from app.recipe_access import get_owned_recipe, get_visible_recipe, is_shared_with


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_user(db, email, is_system=False):
    user = User(email=email, password_hash="x", is_system=is_system)
    db.add(user)
    db.commit()
    return user


def make_recipe(db, user, name="Recipe", **kwargs):
    recipe = Recipe(user_id=user.id, name=name, servings=1, **kwargs)
    db.add(recipe)
    db.commit()
    return recipe


def test_owner_can_view_own_private_recipe(db):
    owner = make_user(db, "owner@example.com")
    recipe = make_recipe(db, owner)
    result = get_visible_recipe(recipe.id, owner, db)
    assert result.id == recipe.id


def test_public_recipe_visible_to_anyone(db):
    owner = make_user(db, "owner@example.com")
    other = make_user(db, "other@example.com")
    recipe = make_recipe(db, owner, is_public=True)
    result = get_visible_recipe(recipe.id, other, db)
    assert result.id == recipe.id


def test_system_stock_recipe_visible_to_anyone(db):
    system_user = make_user(db, "stock@example.com", is_system=True)
    other = make_user(db, "other@example.com")
    recipe = make_recipe(db, system_user, is_public=True, import_slug="stock_test")
    result = get_visible_recipe(recipe.id, other, db)
    assert result.id == recipe.id


def test_shared_recipe_visible_to_the_recipient(db):
    owner = make_user(db, "owner@example.com")
    recipient = make_user(db, "recipient@example.com")
    recipe = make_recipe(db, owner)
    db.add(RecipeShare(recipe_id=recipe.id, shared_with_user_id=recipient.id))
    db.commit()

    assert is_shared_with(recipe.id, recipient.id, db) is True
    result = get_visible_recipe(recipe.id, recipient, db)
    assert result.id == recipe.id


def test_inaccessible_private_recipe_raises_404(db):
    owner = make_user(db, "owner@example.com")
    stranger = make_user(db, "stranger@example.com")
    recipe = make_recipe(db, owner)

    with pytest.raises(HTTPException) as exc_info:
        get_visible_recipe(recipe.id, stranger, db)
    assert exc_info.value.status_code == 404


def test_nonexistent_recipe_raises_404(db):
    stranger = make_user(db, "stranger@example.com")
    with pytest.raises(HTTPException) as exc_info:
        get_visible_recipe(999999, stranger, db)
    assert exc_info.value.status_code == 404


def test_inaccessible_and_nonexistent_produce_identical_error_bodies(db):
    """A guessed private recipe ID must not be distinguishable from a
    nonexistent one — same status code and same detail message."""
    owner = make_user(db, "owner@example.com")
    stranger = make_user(db, "stranger@example.com")
    recipe = make_recipe(db, owner)

    with pytest.raises(HTTPException) as private_exc:
        get_visible_recipe(recipe.id, stranger, db)
    with pytest.raises(HTTPException) as missing_exc:
        get_visible_recipe(999999, stranger, db)

    assert private_exc.value.status_code == missing_exc.value.status_code == 404
    assert private_exc.value.detail == missing_exc.value.detail


def test_get_owned_recipe_rejects_non_owner_even_if_shared(db):
    """get_owned_recipe is the stricter, mutating-operation check —
    being shared-with or public is not enough, only the owner passes."""
    owner = make_user(db, "owner@example.com")
    recipient = make_user(db, "recipient@example.com")
    recipe = make_recipe(db, owner, is_public=True)
    db.add(RecipeShare(recipe_id=recipe.id, shared_with_user_id=recipient.id))
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_owned_recipe(recipe.id, recipient, db)
    assert exc_info.value.status_code == 404

    assert get_owned_recipe(recipe.id, owner, db).id == recipe.id
