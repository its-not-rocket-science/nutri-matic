"""Idempotent, batched purge of expired demo accounts and every row that
depends on them (public-launch hardening prompt 2).

SAFETY: this deletes real rows from a real database. Dry-run is the
default; `--apply` is required to actually delete anything, and the
SAFETY GATE in this repo's own EXECUTION SAFETY REQUIREMENTS (see
prompts.txt / docs/demo-lifecycle.md) requires a human to review a
dry-run's exact output against production before the first `--apply`
run there. This module has no way to skip that review — it only
refuses to run destructively without `--apply` being passed explicitly.

Usage:
    python -m app.demo_purge report                    # counts only, no deletion
    python -m app.demo_purge purge                      # dry-run (default) — reports
                                                          # exactly which accounts/rows
                                                          # would be deleted
    python -m app.demo_purge purge --apply               # actually deletes
    python -m app.demo_purge purge --apply --batch-size 200

Deletion order matters: no table in this schema declares `ON DELETE
CASCADE` (verified against models.py — every FK to `users.id` is a
plain, restrict-by-default reference), so every dependent row must be
removed before the row it depends on, in explicit application code
rather than relying on the database to cascade for us. See
docs/demo-lifecycle.md for the full dependency map this follows.

Batched by user id so a large backlog doesn't hold one long lock or one
unbounded transaction — each batch of `--batch-size` expired users is
deleted and committed independently, and a failure partway through
leaves earlier batches purged and later ones untouched (safe to just
re-run — already-deleted users simply won't be selected again).
"""

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .database import SessionLocal
from .demo_lifecycle import is_expired_demo
from .models import (
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

_logger = logging.getLogger("app.demo")

DEFAULT_BATCH_SIZE = 100


@dataclass
class BatchResult:
    user_ids: list[int]
    emails: list[str]
    row_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class PurgeReport:
    dry_run: bool
    batches: list[BatchResult]
    duration_seconds: float = 0.0

    @property
    def total_users(self) -> int:
        return sum(len(b.user_ids) for b in self.batches)

    @property
    def total_rows(self) -> int:
        return sum(sum(b.row_counts.values()) for b in self.batches)


def _expired_demo_users_query(db: Session, now: datetime):
    # is_expired_demo's own logic, expressed as a query rather than
    # per-row in Python — must stay equivalent to that function (tests
    # cover both), since this is what actually selects purge candidates.
    return db.query(User.id, User.email).filter(
        User.is_demo.is_(True), User.expires_at.isnot(None), User.expires_at <= now
    ).order_by(User.id)


def _expired_demo_user_ids(db: Session, now: datetime, limit: int) -> list[int]:
    return [uid for (uid, _email) in _expired_demo_users_query(db, now).limit(limit).all()]


def _delete_batch(db: Session, user_ids: list[int]) -> dict[str, int]:
    """Deletes one batch of users and every row that depends on them, in
    dependency order, all in the caller's current transaction. Returns a
    per-table row count for reporting. Caller commits (or, for a
    dry-run, never calls this at all)."""
    counts: dict[str, int] = {}

    def _delete(query, label: str) -> None:
        counts[label] = counts.get(label, 0) + query.delete(synchronize_session=False)

    recipe_ids = [rid for (rid,) in db.query(Recipe.id).filter(Recipe.user_id.in_(user_ids)).all()]
    collection_ids = [cid for (cid,) in db.query(Collection.id).filter(Collection.user_id.in_(user_ids)).all()]
    recipe_ingredient_ids = [
        riid for (riid,) in db.query(RecipeIngredient.id).filter(RecipeIngredient.recipe_id.in_(recipe_ids)).all()
    ]

    _delete(
        db.query(RecipeIngredientProvenance).filter(
            RecipeIngredientProvenance.recipe_ingredient_id.in_(recipe_ingredient_ids)
        ),
        "recipe_ingredient_provenance",
    )
    _delete(db.query(RecipeIngredient).filter(RecipeIngredient.recipe_id.in_(recipe_ids)), "recipe_ingredients")
    _delete(
        db.query(RecipeRating).filter(
            or_(RecipeRating.recipe_id.in_(recipe_ids), RecipeRating.user_id.in_(user_ids))
        ),
        "recipe_ratings",
    )
    _delete(
        db.query(RecipeComment).filter(
            or_(RecipeComment.recipe_id.in_(recipe_ids), RecipeComment.user_id.in_(user_ids))
        ),
        "recipe_comments",
    )
    _delete(db.query(RecipeTag).filter(RecipeTag.recipe_id.in_(recipe_ids)), "recipe_tags")
    _delete(
        db.query(RecipeShare).filter(
            or_(RecipeShare.recipe_id.in_(recipe_ids), RecipeShare.shared_with_user_id.in_(user_ids))
        ),
        "recipe_shares",
    )
    _delete(
        db.query(CollectionRecipe).filter(
            or_(CollectionRecipe.recipe_id.in_(recipe_ids), CollectionRecipe.collection_id.in_(collection_ids))
        ),
        "collection_recipes",
    )
    _delete(db.query(RobustnessResult).filter(RobustnessResult.recipe_id.in_(recipe_ids)), "robustness_results")
    _delete(db.query(Recipe).filter(Recipe.id.in_(recipe_ids)), "recipes")
    _delete(db.query(Collection).filter(Collection.id.in_(collection_ids)), "collections")

    meal_plan_template_ids = [
        tid for (tid,) in db.query(MealPlanTemplate.id).filter(MealPlanTemplate.user_id.in_(user_ids)).all()
    ]
    _delete(
        db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.template_id.in_(meal_plan_template_ids)),
        "meal_plan_template_entries",
    )
    _delete(db.query(MealPlanTemplate).filter(MealPlanTemplate.id.in_(meal_plan_template_ids)), "meal_plan_templates")

    diary_meal_template_ids = [
        tid for (tid,) in db.query(DiaryMealTemplate.id).filter(DiaryMealTemplate.user_id.in_(user_ids)).all()
    ]
    _delete(
        db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.template_id.in_(diary_meal_template_ids)),
        "diary_meal_template_items",
    )
    _delete(db.query(DiaryMealTemplate).filter(DiaryMealTemplate.id.in_(diary_meal_template_ids)), "diary_meal_templates")

    _delete(db.query(DiaryEntry).filter(DiaryEntry.user_id.in_(user_ids)), "diary_entries")
    _delete(db.query(DiarySnapshot).filter(DiarySnapshot.user_id.in_(user_ids)), "diary_snapshots")
    _delete(db.query(MealPlanEntry).filter(MealPlanEntry.user_id.in_(user_ids)), "meal_plan_entries")
    _delete(db.query(WeightLog).filter(WeightLog.user_id.in_(user_ids)), "weight_logs")
    _delete(db.query(FoodPrice).filter(FoodPrice.user_id.in_(user_ids)), "food_prices")
    _delete(db.query(SavedFilterPreset).filter(SavedFilterPreset.user_id.in_(user_ids)), "saved_filter_presets")
    _delete(db.query(DietaryConstraint).filter(DietaryConstraint.user_id.in_(user_ids)), "dietary_constraints")
    _delete(db.query(ApiKey).filter(ApiKey.user_id.in_(user_ids)), "api_keys")
    _delete(
        db.query(ClinicianClientLink).filter(
            or_(
                ClinicianClientLink.clinician_user_id.in_(user_ids),
                ClinicianClientLink.client_user_id.in_(user_ids),
            )
        ),
        "clinician_client_links",
    )
    _delete(
        db.query(ClinicianNote).filter(
            or_(ClinicianNote.clinician_user_id.in_(user_ids), ClinicianNote.client_user_id.in_(user_ids))
        ),
        "clinician_notes",
    )

    _delete(db.query(Profile).filter(Profile.user_id.in_(user_ids)), "profiles")
    _delete(db.query(User).filter(User.id.in_(user_ids)), "users")

    return {k: v for k, v in counts.items() if v}


def purge_expired_demo_accounts(
    db: Session, *, dry_run: bool = True, batch_size: int = DEFAULT_BATCH_SIZE, now: datetime | None = None
) -> PurgeReport:
    """Idempotent: users already deleted in a prior run simply won't be
    selected again. Safe to call repeatedly, including concurrently —
    each batch is its own transaction, and two overlapping runs racing
    for the same batch just means one of them deletes zero rows for any
    user id the other already removed (a delete-by-id-list matching zero
    rows is a no-op, not an error)."""
    now = now if now is not None else datetime.now(timezone.utc)
    started = datetime.now(timezone.utc)
    batches: list[BatchResult] = []

    if dry_run:
        # Read-only, so there's no reason to bound this to one batch the
        # way the destructive path must — every matching row is reported
        # (chunked into batch_size-sized groups purely for readability),
        # since the whole point is a human reviewing the complete list,
        # not a sample of it.
        rows = _expired_demo_users_query(db, now).all()
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            batches.append(BatchResult(user_ids=[uid for uid, _ in chunk], emails=[e for _, e in chunk]))
        return PurgeReport(dry_run=True, batches=batches, duration_seconds=0.0)

    while True:
        user_ids = _expired_demo_user_ids(db, now, batch_size)
        if not user_ids:
            break

        emails = [e for (e,) in db.query(User.email).filter(User.id.in_(user_ids)).all()]
        row_counts = _delete_batch(db, user_ids)
        db.commit()
        _logger.info(
            "demo_purge_batch",
            extra={"user_count": len(user_ids), "row_counts": row_counts},
        )
        batches.append(BatchResult(user_ids=user_ids, emails=emails, row_counts=row_counts))

        if len(user_ids) < batch_size:
            break

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    return PurgeReport(dry_run=dry_run, batches=batches, duration_seconds=duration)


def count_would_purge(db: Session, now: datetime | None = None) -> int:
    now = now if now is not None else datetime.now(timezone.utc)
    return (
        db.query(User.id)
        .filter(User.is_demo.is_(True), User.expires_at.isnot(None), User.expires_at <= now)
        .count()
    )


def demo_account_counts(db: Session, now: datetime | None = None) -> dict[str, int]:
    """The 'emergency operational command' counts: total/active/expired
    demo accounts, independent of the purge job itself."""
    now = now if now is not None else datetime.now(timezone.utc)
    total = db.query(User.id).filter(User.is_demo.is_(True)).count()
    expired = count_would_purge(db, now=now)
    return {"total_demo_accounts": total, "expired_demo_accounts": expired, "active_demo_accounts": total - expired}


def _cmd_report(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        counts = demo_account_counts(db)
        print(f"Total demo accounts:   {counts['total_demo_accounts']}")
        print(f"Active demo accounts:  {counts['active_demo_accounts']}")
        print(f"Expired demo accounts: {counts['expired_demo_accounts']} (pending purge)")
    finally:
        db.close()


def _cmd_purge(args: argparse.Namespace) -> None:
    db = SessionLocal()
    try:
        dry_run = not args.apply
        report = purge_expired_demo_accounts(db, dry_run=dry_run, batch_size=args.batch_size)
        if dry_run:
            print(f"DRY RUN — would purge {report.total_users} expired demo account(s). No rows deleted.")
            for batch in report.batches:
                for user_id, email in zip(batch.user_ids, batch.emails):
                    print(f"    user_id={user_id} email={email}")
            print(
                "Re-run with --apply only after a human has reviewed the account list above "
                "(see EXECUTION SAFETY REQUIREMENTS / docs/demo-lifecycle.md)."
            )
        else:
            print(f"Purged {report.total_users} demo account(s), {report.total_rows} dependent row(s) total.")
            for i, batch in enumerate(report.batches, start=1):
                print(f"  Batch {i}: {len(batch.user_ids)} accounts, rows: {batch.row_counts}")
            print(f"Duration: {report.duration_seconds:.2f}s")
    finally:
        db.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="Print active/expired/total demo-account counts.")
    report_parser.set_defaults(func=_cmd_report)

    purge_parser = subparsers.add_parser("purge", help="Purge expired demo accounts (dry-run by default).")
    purge_parser.add_argument(
        "--apply", action="store_true", help="Actually delete. Without this, always dry-run."
    )
    purge_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    purge_parser.set_defaults(func=_cmd_purge)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
