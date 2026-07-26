"""One-off, human-reviewed identification of demo accounts that predate
`User.is_demo` (public-launch hardening prompt 2's migration,
92158621e2f3, deliberately leaves every existing row `is_demo=false` —
see that migration's docstring for why marking pre-existing rows isn't
folded into it).

SAFETY: this repo's production database already contains real demo
accounts from manual testing (see EXECUTION SAFETY REQUIREMENTS in
prompts.txt). Do not run this with --apply against production without
first running it without --apply and having a human review every row
it proposes to mark — the printed dry-run output IS that review
artifact.

Heuristic (deliberately conservative — both signals must hold, not
either alone):

1. Email under demo_data.DEMO_EMAIL_DOMAIN. This alone is not proof: a
   real caller could register a normal account with an email under this
   domain (register() never validates email ownership or restricts its
   domain) — attacker-controlled or just coincidental, either way it
   would be wrong to trust the domain in isolation forever.
2. Every one of sex/activity_level/weight_kg/height_cm exactly matches
   demo_data.py's hard-coded seed values ("female"/"moderate"/65.0/168.0).
   A real registration never sets any profile field at signup time
   (register() only takes email+password — see routers/auth.py), so a
   real account matching the email pattern would have every one of
   these fields NULL, not this exact combination. Requiring all four to
   match exactly makes a coincidental false match on a real account
   extremely unlikely.

A row matching the email pattern but NOT every profile-field signal is
reported separately, as "ambiguous — not auto-marked", for a human to
investigate by hand rather than silently guessed at either way.

Usage:
    python -m app.backfill_demo_flag              # dry-run (default) — prints every match
    python -m app.backfill_demo_flag --apply       # marks confirmed matches is_demo=true
                                                    # and sets expires_at from their actual
                                                    # created_at (immediately purge-eligible
                                                    # if that's already in the past — expected
                                                    # for old manual-testing accounts)
"""

import argparse

from .database import SessionLocal
from .demo_data import DEMO_EMAIL_DOMAIN
from .demo_lifecycle import demo_expiry_from
from .models import User

_SEED_SEX = "female"
_SEED_ACTIVITY_LEVEL = "moderate"
_SEED_WEIGHT_KG = 65.0
_SEED_HEIGHT_CM = 168.0


def _matches_seed_profile(user: User) -> bool:
    return (
        user.sex == _SEED_SEX
        and user.activity_level == _SEED_ACTIVITY_LEVEL
        and user.weight_kg == _SEED_WEIGHT_KG
        and user.height_cm == _SEED_HEIGHT_CM
    )


def find_candidates(db) -> tuple[list[User], list[User]]:
    """Returns (confirmed, ambiguous) — users whose email is under the
    demo domain, split by whether their profile fields also match the
    seeded demo defaults exactly."""
    email_matches = db.query(User).filter(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}"), User.is_demo.is_(False)).all()
    confirmed = [u for u in email_matches if _matches_seed_profile(u)]
    ambiguous = [u for u in email_matches if not _matches_seed_profile(u)]
    return confirmed, ambiguous


def apply_backfill(db, confirmed: list[User]) -> int:
    for user in confirmed:
        user.is_demo = True
        user.expires_at = demo_expiry_from(user.created_at)
    db.commit()
    return len(confirmed)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Actually mark confirmed matches. Without this, dry-run.")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        confirmed, ambiguous = find_candidates(db)

        print(f"Confirmed demo-account matches (email + full profile-field match): {len(confirmed)}")
        for u in confirmed:
            print(f"    user_id={u.id} email={u.email} created_at={u.created_at.isoformat()}")

        print(f"\nAmbiguous — email matches but profile fields don't (NOT auto-marked): {len(ambiguous)}")
        for u in ambiguous:
            print(
                f"    user_id={u.id} email={u.email} sex={u.sex!r} activity_level={u.activity_level!r} "
                f"weight_kg={u.weight_kg!r} height_cm={u.height_cm!r}"
            )

        if not args.apply:
            print("\nDRY RUN — no rows changed. Re-run with --apply only after a human has reviewed the lists above.")
            return

        n = apply_backfill(db, confirmed)
        print(f"\nMarked {n} account(s) is_demo=true.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
