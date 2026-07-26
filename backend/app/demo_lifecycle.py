"""Shared demo-account lifecycle constants and helpers (public-launch
hardening prompt 2). Used by:

- demo_data.py — sets is_demo/expires_at at creation time.
- auth.py — rejects an expired demo account's token the same way any
  other invalid/expired token is rejected (no distinguishing detail).
- demo_purge.py — deletes expired demo accounts and their dependent data.
- backfill_demo_flag.py — the separate, human-reviewed identification
  step for demo accounts that predate this feature (see that module and
  the migration's docstring for why this is deliberately not automatic).

See docs/demo-lifecycle.md for the full operational picture.
"""

import os
from datetime import datetime, timedelta, timezone

from .models import User

# 24h default per the public-launch hardening prompt's suggestion — also
# matches the existing JWT access-token expiry (see auth.py), so a demo
# session's token and its account naturally expire together in the
# common case rather than one silently outliving the other by design.
DEMO_LIFETIME_HOURS = float(os.environ.get("DEMO_LIFETIME_HOURS", "24"))


def demo_expiry_from(created_at: datetime) -> datetime:
    return created_at + timedelta(hours=DEMO_LIFETIME_HOURS)


def is_expired_demo(user: User, now: datetime | None = None) -> bool:
    """True only for a demo account whose expiry has passed. A non-demo
    user is never expired through this mechanism, regardless of
    expires_at (which is always null for them) — see User.is_demo's
    docstring."""
    if not user.is_demo or user.expires_at is None:
        return False
    now = now if now is not None else datetime.now(timezone.utc)
    expires_at = user.expires_at
    # SQLite (this project's test suite; production is Postgres) doesn't
    # actually store timezone info even for a DateTime(timezone=True)
    # column — a row read back after a round trip through it comes back
    # naive. This value was only ever written as UTC (demo_expiry_from
    # always operates on an aware UTC datetime), so naive here means UTC,
    # not "unknown".
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return now >= expires_at
