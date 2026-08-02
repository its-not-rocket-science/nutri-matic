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

Three gaps here were caught by an automated PR review, not written
correctly the first time: (1) a demo-owned recipe can be logged in
*another* user's diary/meal-plan/template via is_public/RecipeShare —
those consumer rows must be cleared before the recipe is deleted,
regardless of who owns them, or the delete aborts the whole batch; (2)
`medical_recommendation_acknowledgements` (profile_id FK) was missing
entirely and blocks deleting a profile that has one; (3) the API-key
auth path (`api_keys.get_api_key_user`) checked identity but not demo
expiry, so an expired demo could keep using a key it created before
expiring, indefinitely if scheduled purges stay dry-run-only. All three
fixed; see this module's git history / PR review for the exact findings.

Batched by user id so a large backlog doesn't hold one long lock or one
unbounded transaction — each batch of `--batch-size` expired users is
deleted and committed independently, and a failure partway through
leaves earlier batches purged and later ones untouched (safe to just
re-run — already-deleted users simply won't be selected again).
"""

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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

_logger = logging.getLogger("app.demo")

DEFAULT_BATCH_SIZE = 100
# operational-hardening prompt 1, requirement 7: an account is eligible
# only once it's been expired for at least this long, not at the exact
# expiry instant — a buffer against clock skew across the fleet (auth
# already blocks an expired demo immediately regardless of this; this
# only delays the *deletion*) and a small window for investigating a
# report about an account shortly before it would otherwise vanish.
# Overridable via DEMO_PURGE_GRACE_PERIOD_HOURS for operational tuning
# without a code change; 30 minutes is comfortably longer than any
# reasonable clock drift and short enough not to meaningfully extend how
# long an expired demo account's data lingers (still governed by the
# same DEMO_LIFETIME_HOURS=24 default as the account's own lifetime).
DEFAULT_GRACE_PERIOD_HOURS = float(os.environ.get("DEMO_PURGE_GRACE_PERIOD_HOURS", "0.5"))
# requirement 8: bounds one invocation's work regardless of backlog size
# — each batch is already its own transaction (never one unbounded
# transaction), but an unbounded number of batches in a single run could
# still monopolise a scheduled job's time budget. A capped run reports
# how many remain; the next scheduled run picks up where this one left
# off (purge_expired_demo_accounts's usual re-query-each-batch behaviour
# already makes this safe — nothing here assumes a single run finishes
# the whole backlog). 50 batches * 100/batch = 5,000 accounts/run, far
# beyond any realistic nightly backlog for this app's actual demo volume.
DEFAULT_MAX_BATCHES_PER_RUN = 50


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
    # requirement 8: True when this run stopped because it hit
    # max_batches, not because the backlog was exhausted — the caller
    # (scheduled workflow) should expect the next run to continue where
    # this one left off, not assume the backlog is clear.
    hit_batch_limit: bool = False
    # requirement 9's "remaining expired count" — computed after this
    # run finishes (whether it exhausted the backlog or hit the batch
    # limit), so a summary log/report always answers "is there more work
    # outstanding" without a separate manual query.
    remaining_expired: int = 0

    @property
    def total_users(self) -> int:
        return sum(len(b.user_ids) for b in self.batches)

    @property
    def total_rows(self) -> int:
        return sum(sum(b.row_counts.values()) for b in self.batches)


def _eligible_before(now: datetime, grace_period_hours: float) -> datetime:
    return now - timedelta(hours=grace_period_hours)


def _expired_demo_users_query(db: Session, eligible_before: datetime):
    # is_expired_demo's own logic (plus the grace-period offset the
    # caller already folded into eligible_before), expressed as a query
    # rather than per-row in Python — must stay equivalent to that
    # function modulo the grace period (tests cover both), since this is
    # what actually selects purge candidates.
    return db.query(User.id, User.email).filter(
        User.is_demo.is_(True), User.expires_at.isnot(None), User.expires_at <= eligible_before
    ).order_by(User.id)


def _expired_demo_user_ids(db: Session, eligible_before: datetime, limit: int) -> list[int]:
    return [uid for (uid, _email) in _expired_demo_users_query(db, eligible_before).limit(limit).all()]


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

    # Anyone (not just this batch's users) can have logged one of these
    # recipes — a demo-owned recipe can be is_public or RecipeShare'd, so
    # another real user's own diary/meal-plan/template entry can
    # reference recipe_id here. Must clear regardless of whose row it is,
    # or Postgres rejects the recipe delete below (restrictive FK) and
    # aborts the whole batch. This is the one place purging a demo
    # account can remove a non-demo user's row — an accepted, documented
    # tradeoff (see docs/demo-lifecycle.md): the alternative is leaving
    # an orphaned recipe with no owner, which isn't valid either
    # (Recipe.user_id is NOT NULL).
    _delete(db.query(DiaryEntry).filter(DiaryEntry.recipe_id.in_(recipe_ids)), "diary_entries")
    _delete(db.query(MealPlanEntry).filter(MealPlanEntry.recipe_id.in_(recipe_ids)), "meal_plan_entries")
    _delete(
        db.query(MealPlanTemplateEntry).filter(MealPlanTemplateEntry.recipe_id.in_(recipe_ids)),
        "meal_plan_template_entries",
    )
    _delete(
        db.query(DiaryMealTemplateItem).filter(DiaryMealTemplateItem.recipe_id.in_(recipe_ids)),
        "diary_meal_template_items",
    )

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

    profile_ids = [pid for (pid,) in db.query(Profile.id).filter(Profile.user_id.in_(user_ids)).all()]
    _delete(
        db.query(MedicalRecommendationAcknowledgement).filter(
            MedicalRecommendationAcknowledgement.profile_id.in_(profile_ids)
        ),
        "medical_recommendation_acknowledgements",
    )
    # prompt 2.1: profile_goals has a plain (non-cascading) FK to profiles,
    # same as every other table in this schema — a demo profile with at
    # least one goal selected would otherwise make Profile deletion below
    # fail its FK constraint and roll back the whole batch.
    _delete(db.query(ProfileGoal).filter(ProfileGoal.profile_id.in_(profile_ids)), "profile_goals")
    _delete(db.query(Profile).filter(Profile.id.in_(profile_ids)), "profiles")
    _delete(db.query(User).filter(User.id.in_(user_ids)), "users")

    return {k: v for k, v in counts.items() if v}


def purge_expired_demo_accounts(
    db: Session,
    *,
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batches: int = DEFAULT_MAX_BATCHES_PER_RUN,
    grace_period_hours: float = DEFAULT_GRACE_PERIOD_HOURS,
    now: datetime | None = None,
) -> PurgeReport:
    """Idempotent: users already deleted in a prior run simply won't be
    selected again. Safe to call repeatedly, including concurrently —
    each batch is its own transaction, and two overlapping runs racing
    for the same batch just means one of them deletes zero rows for any
    user id the other already removed (a delete-by-id-list matching zero
    rows is a no-op, not an error).

    `max_batches` bounds one run's work regardless of backlog size
    (requirement 8) — a run that hits the limit stops with
    `PurgeReport.hit_batch_limit=True` rather than continuing
    indefinitely; the next scheduled run resumes automatically (nothing
    here assumes one run clears the whole backlog). `grace_period_hours`
    delays eligibility past the exact expiry instant (requirement 7).

    Emits one structured `demo_purge_run_summary` log line
    (scanned/deleted/failed/remaining/duration — requirement 9) whether
    or not anything was actually eligible, and — for the destructive
    path — lets any exception from `_delete_batch`/`db.commit()`
    propagate after logging what completed so far, rather than
    swallowing it: batches already committed stay purged (the
    already-documented idempotent/partial-progress behaviour), and the
    caller (CLI/workflow) sees a non-zero exit either way (requirement
    10)."""
    now = now if now is not None else datetime.now(timezone.utc)
    eligible_before = _eligible_before(now, grace_period_hours)
    started = datetime.now(timezone.utc)
    batches: list[BatchResult] = []

    if dry_run:
        # Read-only, so there's no reason to bound this to one batch the
        # way the destructive path must — every matching row is reported
        # (chunked into batch_size-sized groups purely for readability),
        # since the whole point is a human reviewing the complete list,
        # not a sample of it. max_batches doesn't apply here either, for
        # the same reason.
        rows = _expired_demo_users_query(db, eligible_before).all()
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            batches.append(BatchResult(user_ids=[uid for uid, _ in chunk], emails=[e for _, e in chunk]))
        report = PurgeReport(dry_run=True, batches=batches, duration_seconds=0.0, remaining_expired=0)
        _log_run_summary(report, scanned=report.total_users, failed=False)
        return report

    hit_batch_limit = False
    failed = False
    try:
        batch_number = 0
        while True:
            if batch_number >= max_batches:
                hit_batch_limit = True
                break
            user_ids = _expired_demo_user_ids(db, eligible_before, batch_size)
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
            batch_number += 1

            if len(user_ids) < batch_size:
                break
    except Exception:
        failed = True
        raise
    finally:
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        remaining = count_would_purge(db, now=now, grace_period_hours=grace_period_hours)
        report = PurgeReport(
            dry_run=dry_run, batches=batches, duration_seconds=duration,
            hit_batch_limit=hit_batch_limit, remaining_expired=remaining,
        )
        _log_run_summary(report, scanned=report.total_users + remaining, failed=failed)

    return report


def _log_run_summary(report: PurgeReport, *, scanned: int, failed: bool) -> None:
    """The one required structured summary line per run (requirement 9)
    — counts only, never account emails (those stay in the per-batch dry-
    run console report/`_cmd_purge`'s human-review output, a deliberately
    separate, manual-trigger-only path)."""
    _logger.info(
        "demo_purge_run_summary",
        extra={
            "dry_run": report.dry_run,
            "scanned": scanned,
            "eligible": scanned,
            "deleted": report.total_users if not report.dry_run else 0,
            "failed": failed,
            "hit_batch_limit": report.hit_batch_limit,
            "remaining_expired": report.remaining_expired,
            "duration_seconds": report.duration_seconds,
        },
    )


def count_would_purge(db: Session, now: datetime | None = None, grace_period_hours: float = DEFAULT_GRACE_PERIOD_HOURS) -> int:
    now = now if now is not None else datetime.now(timezone.utc)
    eligible_before = _eligible_before(now, grace_period_hours)
    return (
        db.query(User.id)
        .filter(User.is_demo.is_(True), User.expires_at.isnot(None), User.expires_at <= eligible_before)
        .count()
    )


def demo_account_counts(db: Session, now: datetime | None = None, grace_period_hours: float = DEFAULT_GRACE_PERIOD_HOURS) -> dict[str, int]:
    """The 'emergency operational command' counts: total/active/expired
    demo accounts, independent of the purge job itself."""
    now = now if now is not None else datetime.now(timezone.utc)
    total = db.query(User.id).filter(User.is_demo.is_(True)).count()
    expired = count_would_purge(db, now=now, grace_period_hours=grace_period_hours)
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
        report = purge_expired_demo_accounts(
            db, dry_run=dry_run, batch_size=args.batch_size,
            max_batches=args.max_batches, grace_period_hours=args.grace_period_hours,
        )
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
            if report.hit_batch_limit:
                print(
                    f"Stopped after {args.max_batches} batch(es) (--max-batches) — "
                    f"{report.remaining_expired} expired account(s) still remain for the next run."
                )
            elif report.remaining_expired:
                # not expected in the common case (the loop only stops
                # early on hit_batch_limit or an empty query), but stated
                # explicitly rather than silently omitted if it ever does
                print(f"{report.remaining_expired} expired account(s) still remain (see logs).")
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
    purge_parser.add_argument(
        "--max-batches", type=int, default=DEFAULT_MAX_BATCHES_PER_RUN,
        help="Stop after this many batches, leaving the rest for the next run (requirement 8).",
    )
    purge_parser.add_argument(
        "--grace-period-hours", type=float, default=DEFAULT_GRACE_PERIOD_HOURS,
        help="Only purge accounts expired for at least this long (requirement 7).",
    )
    purge_parser.set_defaults(func=_cmd_purge)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        # Belt-and-braces on top of the already-non-zero exit an
        # uncaught exception produces by default (operational-hardening
        # prompt 1, requirement 10: "a partial or failed deletion must
        # return a non-zero exit status", "visible to monitoring and
        # GitHub Actions") — an explicit, unambiguous exit code plus a
        # one-line error `_logger` record (structured, so it's the same
        # kind of thing monitoring already watches `app.demo` for),
        # rather than relying solely on Python's default traceback/exit
        # behaviour being "good enough". In `main()` itself (not just the
        # `if __name__ == "__main__":` guard) so it fires the same way
        # whether this runs as a script or is called directly.
        _logger.error("demo_purge_failed", extra={"error": str(exc)})
        print(f"demo_purge failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
