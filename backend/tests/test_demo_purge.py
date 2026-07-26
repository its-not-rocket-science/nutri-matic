from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import demo_purge
from app.database import Base
from app.demo_purge import (
    count_would_purge,
    demo_account_counts,
    main as demo_purge_main,
    purge_expired_demo_accounts,
)
from app.reference_patterns import AMINO_ACIDS
from app.models import (
    ApiKey,
    ClinicianClientLink,
    ClinicianNote,
    Collection,
    CollectionRecipe,
    DiaryEntry,
    DiaryMealTemplate,
    DiaryMealTemplateItem,
    DiarySnapshot,
    DietaryConstraint,
    Food,
    FoodPrice,
    MealPlanEntry,
    MealPlanTemplate,
    MealPlanTemplateEntry,
    Profile,
    Recipe,
    RecipeComment,
    RecipeIngredient,
    RecipeIngredientProvenance,
    RecipeRating,
    RecipeShare,
    RecipeTag,
    RobustnessResult,
    SavedFilterPreset,
    User,
    WeightLog,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def make_demo_user(db, *, expired: bool, email="demo-1@demo.nutrimatic.local") -> User:
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    user = User(email=email, password_hash="x", is_demo=True, expires_at=expires_at)
    db.add(user)
    db.flush()
    return user


def make_real_user(db, email="real@example.com") -> User:
    user = User(email=email, password_hash="x", is_demo=False, expires_at=None)
    db.add(user)
    db.flush()
    return user


def test_active_demo_account_is_not_purged(db):
    make_demo_user(db, expired=False)
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 0
    assert db.query(User).count() == 1


def test_non_demo_user_is_never_purged(db):
    make_real_user(db)
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 0
    assert db.query(User).count() == 1


def test_dry_run_reports_specific_accounts_and_writes_nothing(db):
    user = make_demo_user(db, expired=True, email="demo-a@demo.nutrimatic.local")
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=True)
    assert report.total_users == 1
    assert report.batches[0].user_ids == [user.id]
    assert report.batches[0].emails == ["demo-a@demo.nutrimatic.local"]
    assert db.query(User).count() == 1  # nothing deleted


def test_purge_removes_expired_demo_and_leaves_others_untouched(db):
    expired_demo = make_demo_user(db, expired=True, email="expired@demo.nutrimatic.local")
    active_demo = make_demo_user(db, expired=False, email="active@demo.nutrimatic.local")
    real_user = make_real_user(db)
    db.commit()
    expired_demo_id, active_demo_id, real_user_id = expired_demo.id, active_demo.id, real_user.id

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 1
    assert db.query(User).filter(User.id == expired_demo_id).one_or_none() is None
    assert db.query(User).filter(User.id == active_demo_id).one_or_none() is not None
    assert db.query(User).filter(User.id == real_user_id).one_or_none() is not None


def test_purge_is_idempotent(db):
    make_demo_user(db, expired=True)
    db.commit()

    first = purge_expired_demo_accounts(db, dry_run=False)
    second = purge_expired_demo_accounts(db, dry_run=False)
    assert first.total_users == 1
    assert second.total_users == 0
    assert db.query(User).count() == 0


def test_purge_batches_across_multiple_rounds(db):
    for i in range(5):
        make_demo_user(db, expired=True, email=f"demo-{i}@demo.nutrimatic.local")
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=False, batch_size=2)
    assert report.total_users == 5
    assert len(report.batches) == 3  # 2 + 2 + 1
    assert db.query(User).count() == 0


def test_demo_account_counts(db):
    make_demo_user(db, expired=True, email="e@demo.nutrimatic.local")
    make_demo_user(db, expired=False, email="a@demo.nutrimatic.local")
    make_real_user(db)
    db.commit()

    counts = demo_account_counts(db)
    assert counts == {"total_demo_accounts": 2, "active_demo_accounts": 1, "expired_demo_accounts": 1}
    assert count_would_purge(db) == 1


def test_purge_removes_every_dependent_row_across_the_full_schema(db):
    """A demo account is a full, real account — it can touch every
    feature via the API before expiring, not just what demo_data.py
    seeds. Builds one row in every table that references the user
    (directly, via an owned recipe, or via an owned collection) and
    confirms the purge clears all of it, plus a control user's
    equivalent rows survive untouched."""
    demo = make_demo_user(db, expired=True, email="full@demo.nutrimatic.local")
    other = make_real_user(db, email="other@example.com")
    db.add(Food(
        id=1, name="Test food", data_type="sr_legacy_food", protein_g_per_100g=10,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 5),
    ))
    db.flush()

    demo_profile = Profile(user_id=demo.id, name="Me", is_account_owner=True)
    other_profile = Profile(user_id=other.id, name="Me", is_account_owner=True)
    db.add_all([demo_profile, other_profile])
    db.flush()

    demo_recipe = Recipe(user_id=demo.id, name="Demo recipe", servings=1)
    other_recipe = Recipe(user_id=other.id, name="Other's recipe", servings=1)
    db.add_all([demo_recipe, other_recipe])
    db.flush()

    demo_ingredient = RecipeIngredient(recipe_id=demo_recipe.id, food_id=1, quantity_g=100)
    db.add(demo_ingredient)
    db.flush()
    db.add(RecipeIngredientProvenance(recipe_ingredient_id=demo_ingredient.id, raw_text="100g test food"))

    demo_collection = Collection(user_id=demo.id, name="Demo collection")
    db.add(demo_collection)
    db.flush()
    db.add(CollectionRecipe(collection_id=demo_collection.id, recipe_id=demo_recipe.id))

    # demo user rating/commenting/sharing on the OTHER user's recipe —
    # must be cleared too (user_id side of the FK), and demo sharing
    # their own recipe TO the other user.
    db.add(RecipeRating(recipe_id=other_recipe.id, user_id=demo.id, rating=5))
    db.add(RecipeComment(recipe_id=other_recipe.id, user_id=demo.id, body="nice"))
    db.add(RecipeTag(recipe_id=demo_recipe.id, tag="quick"))
    db.add(RecipeShare(recipe_id=demo_recipe.id, shared_with_user_id=other.id))
    db.add(RobustnessResult(
        recipe_id=demo_recipe.id, model_version="v1", simulation_count=100, random_seed=1,
        metrics={}, overall_explanation="ok",
    ))

    db.add(DiaryEntry(user_id=demo.id, profile_id=demo_profile.id, entry_date=datetime.now().date(), meal="lunch", food_id=1, quantity_g=100))
    db.add(DiarySnapshot(
        user_id=demo.id, profile_id=demo_profile.id, entry_date=datetime.now().date(),
        summary_json={}, drv_methodology_version="v1", scoring_methodology_version="v1",
    ))
    db.add(MealPlanEntry(user_id=demo.id, profile_id=demo_profile.id, plan_date=datetime.now().date(), meal="lunch", food_id=1, quantity_g=100))
    db.add(WeightLog(user_id=demo.id, profile_id=demo_profile.id, log_date=datetime.now().date(), weight_kg=70))
    db.add(FoodPrice(user_id=demo.id, food_id=1, package_price=1.0, package_quantity_g=100))
    db.add(SavedFilterPreset(user_id=demo.id, name="preset", scope="food", filters=[]))
    db.add(DietaryConstraint(user_id=demo.id, category="allergy", tag="peanuts"))
    db.add(ApiKey(user_id=demo.id, name="key", key_hash="h", key_prefix="p"))

    mp_template = MealPlanTemplate(user_id=demo.id, name="template")
    db.add(mp_template)
    db.flush()
    db.add(MealPlanTemplateEntry(template_id=mp_template.id, day_offset=0, meal="lunch", food_id=1, quantity_g=100))

    diary_template = DiaryMealTemplate(user_id=demo.id, name="template")
    db.add(diary_template)
    db.flush()
    db.add(DiaryMealTemplateItem(template_id=diary_template.id, food_id=1, quantity_g=100))

    db.add(ClinicianClientLink(clinician_user_id=other.id, client_user_id=demo.id, status="active"))
    db.add(ClinicianNote(clinician_user_id=other.id, client_user_id=demo.id, note_text="note"))

    # control rows for the OTHER (non-demo) user, which must all survive
    other_profile_id = other_profile.id
    db.add(WeightLog(user_id=other.id, profile_id=other_profile_id, log_date=datetime.now().date(), weight_kg=80))
    db.add(FoodPrice(user_id=other.id, food_id=1, package_price=2.0, package_quantity_g=100))

    db.commit()

    # Captured before purge — expire_on_commit means these ORM objects'
    # attributes would otherwise need a re-SELECT after the row is gone,
    # which raises ObjectDeletedError rather than just reading a plain int.
    demo_id, other_id = demo.id, other.id
    demo_recipe_id, other_recipe_id = demo_recipe.id, other_recipe.id
    demo_ingredient_id, demo_collection_id = demo_ingredient.id, demo_collection.id
    mp_template_id, diary_template_id = mp_template.id, diary_template.id

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 1

    assert db.query(User).filter(User.id == demo_id).one_or_none() is None
    assert db.query(Profile).filter(Profile.user_id == demo_id).count() == 0
    assert db.query(Recipe).filter(Recipe.id == demo_recipe_id).one_or_none() is None
    assert db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id == demo_recipe_id).count() == 0
    assert db.query(RecipeIngredientProvenance).filter(
        RecipeIngredientProvenance.recipe_ingredient_id == demo_ingredient_id
    ).count() == 0
    assert db.query(Collection).filter(Collection.id == demo_collection_id).one_or_none() is None
    assert db.query(CollectionRecipe).filter(CollectionRecipe.collection_id == demo_collection_id).count() == 0
    assert db.query(RecipeRating).filter(RecipeRating.user_id == demo_id).count() == 0
    assert db.query(RecipeComment).filter(RecipeComment.user_id == demo_id).count() == 0
    assert db.query(RecipeTag).filter(RecipeTag.recipe_id == demo_recipe_id).count() == 0
    assert db.query(RecipeShare).filter(RecipeShare.recipe_id == demo_recipe_id).count() == 0
    assert db.query(RobustnessResult).filter(RobustnessResult.recipe_id == demo_recipe_id).count() == 0
    assert db.query(DiaryEntry).filter(DiaryEntry.user_id == demo_id).count() == 0
    assert db.query(DiarySnapshot).filter(DiarySnapshot.user_id == demo_id).count() == 0
    assert db.query(MealPlanEntry).filter(MealPlanEntry.user_id == demo_id).count() == 0
    assert db.query(WeightLog).filter(WeightLog.user_id == demo_id).count() == 0
    assert db.query(FoodPrice).filter(FoodPrice.user_id == demo_id).count() == 0
    assert db.query(SavedFilterPreset).filter(SavedFilterPreset.user_id == demo_id).count() == 0
    assert db.query(DietaryConstraint).filter(DietaryConstraint.user_id == demo_id).count() == 0
    assert db.query(ApiKey).filter(ApiKey.user_id == demo_id).count() == 0
    assert db.query(MealPlanTemplate).filter(MealPlanTemplate.id == mp_template_id).one_or_none() is None
    assert db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id == mp_template_id).count() == 0
    assert db.query(DiaryMealTemplate).filter(DiaryMealTemplate.id == diary_template_id).one_or_none() is None
    assert db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id == diary_template_id).count() == 0
    assert db.query(ClinicianClientLink).filter(ClinicianClientLink.client_user_id == demo_id).count() == 0
    assert db.query(ClinicianNote).filter(ClinicianNote.client_user_id == demo_id).count() == 0

    # the other user and their recipe/rows survive
    assert db.query(User).filter(User.id == other_id).one_or_none() is not None
    assert db.query(Recipe).filter(Recipe.id == other_recipe_id).one_or_none() is not None
    assert db.query(WeightLog).filter(WeightLog.user_id == other_id).count() == 1
    assert db.query(FoodPrice).filter(FoodPrice.user_id == other_id).count() == 1


def test_cli_report_prints_counts(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(demo_purge, "SessionLocal", Session)

    make_demo_user(db, expired=True)
    db.commit()

    demo_purge_main(["report"])
    out = capsys.readouterr().out
    assert "Total demo accounts:   1" in out
    assert "Expired demo accounts: 1" in out


def test_cli_purge_defaults_to_dry_run(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(demo_purge, "SessionLocal", Session)

    user = make_demo_user(db, expired=True, email="cli-dry@demo.nutrimatic.local")
    db.commit()

    demo_purge_main(["purge"])
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "cli-dry@demo.nutrimatic.local" in out
    assert db.query(User).filter(User.id == user.id).one_or_none() is not None


def test_cli_purge_apply_actually_deletes(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(demo_purge, "SessionLocal", Session)

    user = make_demo_user(db, expired=True)
    db.commit()
    user_id = user.id

    demo_purge_main(["purge", "--apply"])
    out = capsys.readouterr().out
    assert "Purged 1 demo account" in out
    assert db.query(User).filter(User.id == user_id).one_or_none() is None
