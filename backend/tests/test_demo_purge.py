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
    MedicalRecommendationAcknowledgement,
    Profile,
    ProfileGoal,
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
    # PR review: a dry-run deletes nothing, so every scanned account is
    # still outstanding — remaining_expired must say so, not a
    # hard-coded 0 (which falsely claimed no work remained). duration
    # must be real elapsed time too, not a hard-coded 0.0.
    assert report.remaining_expired == 1
    assert report.duration_seconds >= 0.0


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


def test_purge_clears_another_users_reference_to_a_demo_owned_recipe(db):
    """A demo-owned recipe can be logged by someone else's diary/meal-plan
    if it was is_public or RecipeShare'd — those consumer rows must be
    cleared before the recipe delete or Postgres rejects it (restrictive
    FK) and aborts the whole batch. Real gap caught by automated PR
    review."""
    demo = make_demo_user(db, expired=True)
    other = make_real_user(db)
    db.add(Food(
        id=1, name="Test food", data_type="sr_legacy_food", protein_g_per_100g=10,
        amino_acids=dict.fromkeys(AMINO_ACIDS, 5),
    ))
    demo_recipe = Recipe(user_id=demo.id, name="Shared demo recipe", servings=1, is_public=True)
    db.add(demo_recipe)
    db.flush()

    other_profile = Profile(user_id=other.id, name="Me", is_account_owner=True)
    db.add(other_profile)
    db.flush()

    # OTHER user's own diary/meal-plan/template entries reference the
    # demo's public recipe — none of these belong to the demo user.
    db.add(DiaryEntry(
        user_id=other.id, profile_id=other_profile.id, entry_date=datetime.now().date(),
        meal="lunch", recipe_id=demo_recipe.id, quantity_servings=1,
    ))
    db.add(MealPlanEntry(
        user_id=other.id, profile_id=other_profile.id, plan_date=datetime.now().date(),
        meal="dinner", recipe_id=demo_recipe.id, quantity_servings=1,
    ))
    other_template = MealPlanTemplate(user_id=other.id, name="other's template")
    db.add(other_template)
    db.flush()
    db.add(MealPlanTemplateEntry(
        template_id=other_template.id, day_offset=0, meal="lunch", recipe_id=demo_recipe.id, quantity_servings=1,
    ))
    other_diary_template = DiaryMealTemplate(user_id=other.id, name="other's diary template")
    db.add(other_diary_template)
    db.flush()
    db.add(DiaryMealTemplateItem(template_id=other_diary_template.id, recipe_id=demo_recipe.id, quantity_servings=1))
    db.commit()

    demo_recipe_id = demo_recipe.id
    other_id = other.id

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 1
    assert db.query(Recipe).filter(Recipe.id == demo_recipe_id).one_or_none() is None
    # the other user's account itself is untouched, even though this one
    # specific cross-referencing row of theirs had to go with the recipe
    assert db.query(User).filter(User.id == other_id).one_or_none() is not None
    assert db.query(DiaryEntry).filter(DiaryEntry.recipe_id == demo_recipe_id).count() == 0
    assert db.query(MealPlanEntry).filter(MealPlanEntry.recipe_id == demo_recipe_id).count() == 0
    assert db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.recipe_id == demo_recipe_id).count() == 0
    assert db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.recipe_id == demo_recipe_id).count() == 0


def test_purge_clears_medical_recommendation_acknowledgements_before_profile(db):
    """medical_recommendation_acknowledgements.profile_id is a non-
    cascading FK missing from an earlier version of _delete_batch —
    deleting a profile with one would fail and abort the batch. Real gap
    caught by automated PR review."""
    demo = make_demo_user(db, expired=True)
    profile = Profile(user_id=demo.id, name="Me", is_account_owner=True)
    db.add(profile)
    db.flush()
    db.add(MedicalRecommendationAcknowledgement(profile_id=profile.id, policy_version=1))
    db.commit()
    profile_id = profile.id

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 1
    assert db.query(MedicalRecommendationAcknowledgement).filter(
        MedicalRecommendationAcknowledgement.profile_id == profile_id
    ).count() == 0
    assert db.query(Profile).filter(Profile.id == profile_id).one_or_none() is None


def test_purge_clears_profile_goals_before_profile(db):
    """profile_goals.profile_id is a non-cascading FK like every other
    table in this schema (prompt 2.1) — deleting a profile with at least
    one selected goal would otherwise fail its FK constraint and abort
    the batch, same class of gap as medical_recommendation_acknowledgements
    above. Caught by automated PR review, not written correctly the first
    time."""
    demo = make_demo_user(db, expired=True)
    profile = Profile(user_id=demo.id, name="Me", is_account_owner=True)
    db.add(profile)
    db.flush()
    db.add(ProfileGoal(profile_id=profile.id, goal="budget", priority=1))
    db.commit()
    profile_id = profile.id

    report = purge_expired_demo_accounts(db, dry_run=False)
    assert report.total_users == 1
    assert db.query(ProfileGoal).filter(ProfileGoal.profile_id == profile_id).count() == 0
    assert db.query(Profile).filter(Profile.id == profile_id).one_or_none() is None


def test_grace_period_defers_purge_past_exact_expiry(db):
    """operational-hardening prompt 1, requirement 7: an account isn't
    eligible at the exact expiry instant — only once expired for at
    least grace_period_hours."""
    now = datetime.now(timezone.utc)
    user = User(
        email="just-expired@demo.nutrimatic.local", password_hash="x", is_demo=True,
        expires_at=now - timedelta(minutes=5),
    )
    db.add(user)
    db.commit()

    within_grace = purge_expired_demo_accounts(db, dry_run=False, grace_period_hours=1.0, now=now)
    assert within_grace.total_users == 0
    assert db.query(User).count() == 1

    past_grace = purge_expired_demo_accounts(db, dry_run=False, grace_period_hours=0.01, now=now)
    assert past_grace.total_users == 1
    assert db.query(User).count() == 0


def test_grace_period_reflected_in_counts_and_remaining(db):
    now = datetime.now(timezone.utc)
    db.add(User(
        email="just-expired@demo.nutrimatic.local", password_hash="x", is_demo=True,
        expires_at=now - timedelta(minutes=5),
    ))
    db.commit()

    assert count_would_purge(db, now=now, grace_period_hours=1.0) == 0
    assert count_would_purge(db, now=now, grace_period_hours=0.01) == 1
    counts = demo_account_counts(db, now=now, grace_period_hours=1.0)
    assert counts["expired_demo_accounts"] == 0
    assert counts["active_demo_accounts"] == 1


def test_negative_grace_period_rejected_by_count_and_report_paths_too(db):
    """PR review's fix lives in _eligible_before, the shared choke point
    — must reject for count_would_purge/demo_account_counts (the
    `report` command's path), not only purge_expired_demo_accounts."""
    with pytest.raises(ValueError):
        count_would_purge(db, grace_period_hours=-0.5)
    with pytest.raises(ValueError):
        demo_account_counts(db, grace_period_hours=-0.5)


def test_max_batches_stops_early_and_reports_remaining(db):
    """requirement 8: one run never processes an unbounded backlog —
    stops after max_batches, flags hit_batch_limit, and reports how many
    are left for the next run to pick up."""
    for i in range(5):
        make_demo_user(db, expired=True, email=f"demo-{i}@demo.nutrimatic.local")
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=False, batch_size=2, max_batches=2)
    assert report.total_users == 4  # 2 batches * 2 — the 5th is left
    assert report.hit_batch_limit is True
    assert report.remaining_expired == 1
    assert db.query(User).count() == 1

    # the next "run" (no max_batches limit this time) finishes the backlog
    follow_up = purge_expired_demo_accounts(db, dry_run=False, batch_size=2)
    assert follow_up.total_users == 1
    assert follow_up.hit_batch_limit is False
    assert follow_up.remaining_expired == 0
    assert db.query(User).count() == 0


def test_max_batches_exact_backlog_boundary_does_not_falsely_report_hit_limit(db):
    """PR review: when the backlog is exactly max_batches * batch_size,
    the final permitted batch clears it completely — the run must not
    then claim hit_batch_limit=True with remaining_expired=0, a
    contradiction (there's nothing left to hit a limit against)."""
    for i in range(4):
        make_demo_user(db, expired=True, email=f"exact-{i}@demo.nutrimatic.local")
    db.commit()

    report = purge_expired_demo_accounts(db, dry_run=False, batch_size=2, max_batches=2)
    assert report.total_users == 4
    assert report.hit_batch_limit is False
    assert report.remaining_expired == 0
    assert db.query(User).count() == 0


def test_negative_grace_period_rejected(db):
    """PR review: a negative grace period moves eligibility into the
    future relative to now, which would delete accounts that haven't
    even expired yet — reject outright rather than let the arithmetic
    silently do the wrong thing."""
    make_demo_user(db, expired=True)
    db.commit()

    with pytest.raises(ValueError):
        purge_expired_demo_accounts(db, dry_run=False, grace_period_hours=-1.0)
    # nothing was deleted — the rejection happens before any query/delete
    assert db.query(User).count() == 1


def test_run_summary_logged_with_counts_never_emails(db, caplog):
    """requirement 9: one structured summary log line per run with
    scanned/deleted/failed/remaining/duration — and, separately,
    requirement 9's 'do not log personal data': no email appears in it,
    even though the dry-run console report (a distinct, human-review-
    only path) does print them deliberately."""
    make_demo_user(db, expired=True, email="summary@demo.nutrimatic.local")
    db.commit()

    with caplog.at_level("INFO", logger="app.demo"):
        purge_expired_demo_accounts(db, dry_run=False)

    summary = next(r for r in caplog.records if r.message == "demo_purge_run_summary")
    assert summary.scanned == 1
    assert summary.deleted == 1
    assert summary.failed is False
    assert summary.remaining_expired == 0
    assert "summary@demo.nutrimatic.local" not in caplog.text


def test_run_summary_logs_failed_true_and_still_reflects_partial_progress(db, monkeypatch, caplog):
    """A batch that raises mid-run must still leave earlier batches
    purged (already covered by idempotency elsewhere) and the summary
    log must say failed=True rather than silently reporting success.

    PR review: on Postgres, a failure inside a real flush/commit leaves
    the session in SQLAlchemy's pending-rollback state, and the finally
    block's own count_would_purge query would raise PendingRollbackError
    there unless purge_expired_demo_accounts rolls back first — masking
    both the original exception and this exact failed=True guarantee.
    SQLite (this file's backend, for speed/no-external-dependency) does
    not reproduce that specific invalidation for a plain RuntimeError
    raised before touching the DB, so this test's real job is confirming
    the *contract* (original exception propagates, summary still logs
    failed=True, earlier batches stay committed) rather than the exact
    Postgres exception type; the db.rollback() fix itself is
    unconditional and correct on both backends regardless."""
    make_demo_user(db, expired=True, email="a@demo.nutrimatic.local")
    make_demo_user(db, expired=True, email="b@demo.nutrimatic.local")
    db.commit()

    call_count = {"n": 0}
    original = demo_purge._delete_batch

    def flaky_delete_batch(db_arg, user_ids):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated failure")
        return original(db_arg, user_ids)

    monkeypatch.setattr(demo_purge, "_delete_batch", flaky_delete_batch)

    with caplog.at_level("INFO", logger="app.demo"):
        with pytest.raises(RuntimeError):
            purge_expired_demo_accounts(db, dry_run=False, batch_size=1)

    summary = next(r for r in caplog.records if r.message == "demo_purge_run_summary")
    assert summary.failed is True
    assert summary.deleted == 1  # the first batch committed before the second raised
    assert db.query(User).count() == 1


def test_cli_purge_apply_respects_max_batches_and_grace_period(db, monkeypatch, capsys):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(demo_purge, "SessionLocal", Session)

    for i in range(3):
        make_demo_user(db, expired=True, email=f"cli-{i}@demo.nutrimatic.local")
    db.commit()

    demo_purge_main(["purge", "--apply", "--batch-size", "1", "--max-batches", "1"])
    out = capsys.readouterr().out
    assert "Purged 1 demo account" in out
    assert "Stopped after 1 batch(es)" in out
    assert "2 expired account(s) still remain" in out
    assert db.query(User).count() == 2


def test_cli_main_exits_non_zero_and_logs_on_failure(db, monkeypatch, caplog):
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(demo_purge, "SessionLocal", Session)
    monkeypatch.setattr(
        demo_purge, "purge_expired_demo_accounts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with caplog.at_level("ERROR", logger="app.demo"):
        with pytest.raises(SystemExit) as exc_info:
            demo_purge.main(["purge", "--apply"])

    assert exc_info.value.code == 1
    assert any(r.message == "demo_purge_failed" for r in caplog.records)


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
