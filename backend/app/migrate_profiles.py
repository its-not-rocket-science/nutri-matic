"""One-off data migration for the household-profiles feature (see
DEPLOYMENT.md's "Household profiles" ALTER TABLE block, which must be run
first). For every existing User:

1. Get-or-creates their "owner" Profile (is_account_owner=True), copying
   the Phase-3 bio/goal fields off the User row. User keeps those columns
   (not dropped — see models.Profile's docstring); this just gives every
   account a real Profile to scope its personal data to going forward.
2. Backfills profile_id on every row of the eight profile-scoped tables
   (dietary_constraints, diary_entries, diary_snapshots, weight_logs,
   meal_plan_entries, meal_plan_templates, diary_meal_templates,
   saved_filter_presets) that matches that user via user_id and still has
   profile_id IS NULL.

Idempotent and safe to re-run: a user who already has an owner profile is
skipped in step 1; a row that already has profile_id set is left alone in
step 2. Reports whether any profile_id IS NULL rows remain afterward —
these should never remain zero-count after a clean run, since every row's
user_id always resolves to some owner profile by then.

Usage:
    python -m app.migrate_profiles [--dry-run]
"""

import argparse

from sqlalchemy import update

from .auth import create_owner_profile
from .database import SessionLocal
from .models import (
    DiaryEntry,
    DiaryMealTemplate,
    DiarySnapshot,
    DietaryConstraint,
    MealPlanEntry,
    MealPlanTemplate,
    Profile,
    SavedFilterPreset,
    User,
    WeightLog,
)

# (model, human-readable label) — every table that gained a profile_id
# column in DEPLOYMENT.md's migration block
PROFILE_SCOPED_TABLES = [
    (DietaryConstraint, "dietary_constraints"),
    (DiaryEntry, "diary_entries"),
    (DiarySnapshot, "diary_snapshots"),
    (WeightLog, "weight_logs"),
    (MealPlanEntry, "meal_plan_entries"),
    (MealPlanTemplate, "meal_plan_templates"),
    (DiaryMealTemplate, "diary_meal_templates"),
    (SavedFilterPreset, "saved_filter_presets"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        users = db.query(User).all()
        created, already_had = 0, 0
        owner_profile_id_by_user_id: dict[int, int] = {}

        for user in users:
            existing = (
                db.query(Profile)
                .filter(Profile.user_id == user.id, Profile.is_account_owner.is_(True))
                .one_or_none()
            )
            if existing is not None:
                owner_profile_id_by_user_id[user.id] = existing.id
                already_had += 1
                continue

            if not args.dry_run:
                profile = create_owner_profile(db, user)
                db.flush()  # need profile.id below, before commit
                owner_profile_id_by_user_id[user.id] = profile.id
            created += 1

        print(f"owner profiles: created={created} already_existed={already_had}")

        if args.dry_run:
            print("(dry run: skipping backfill and commit)")
            return

        for model, label in PROFILE_SCOPED_TABLES:
            updated = 0
            for user_id, profile_id in owner_profile_id_by_user_id.items():
                result = db.execute(
                    update(model)
                    .where(model.user_id == user_id, model.profile_id.is_(None))
                    .values(profile_id=profile_id)
                )
                updated += result.rowcount
            print(f"backfilled {label}: {updated} rows")

        db.commit()

        remaining = 0
        for model, label in PROFILE_SCOPED_TABLES:
            count = db.query(model).filter(model.profile_id.is_(None)).count()
            if count:
                print(f"WARNING: {label} still has {count} row(s) with profile_id IS NULL")
            remaining += count
        print(f"remaining NULL profile_id rows across all tables: {remaining}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
