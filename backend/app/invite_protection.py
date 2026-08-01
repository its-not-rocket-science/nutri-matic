"""Abuse protection for the outbound-email half of
`POST /api/clinician/invites` (routers/clinician.py) — caught by
automated PR review: any registered account (including a free
self-service signup) can otherwise invoke this for unlimited distinct
recipients with arbitrary message text, turning the app's SMTP relay
into an authenticated-but-freely-obtainable spam/phishing channel and
risking quota exhaustion or the sending domain getting blocklisted.

Same two-tier in-process sliding-window shape as demo_protection.py
(per-account here, not per-IP, since this endpoint requires auth):
per-account stops one abusive account from hammering the relay; global
is a circuit breaker capping total invite-email volume across every
caller in the window, so many accounts sending a few each still can't
add up to an unbounded flood. Only guards the branch that actually
sends an email — inviting an already-registered client never emails
anyone, so it isn't rate-limited here."""

import logging
import os

from fastapi import HTTPException

from .rate_limit import SlidingWindowRateLimiter

_invite_logger = logging.getLogger("app.clinician")

# Deliberately generous relative to demo_protection.py's limits: this is
# a real feature real clinicians are expected to use routinely (inviting
# a caseload of clients), not a sandbox endpoint — see DEPLOYMENT.md for
# overriding per deployment.
INVITE_PER_ACCOUNT_LIMIT = int(os.environ.get("INVITE_RATE_LIMIT_PER_ACCOUNT", "20"))
INVITE_PER_ACCOUNT_WINDOW_SECONDS = int(os.environ.get("INVITE_RATE_LIMIT_PER_ACCOUNT_WINDOW_SECONDS", "3600"))
INVITE_GLOBAL_LIMIT = int(os.environ.get("INVITE_RATE_LIMIT_GLOBAL", "200"))
INVITE_GLOBAL_WINDOW_SECONDS = int(os.environ.get("INVITE_RATE_LIMIT_GLOBAL_WINDOW_SECONDS", "3600"))

_GLOBAL_KEY = "global"

_per_account_limiter = SlidingWindowRateLimiter()
_global_limiter = SlidingWindowRateLimiter()

_RATE_LIMIT_DETAIL = "Too many invite emails sent. Try again later."


def enforce_invite_rate_limit(clinician_user_id: int) -> None:
    """Raises HTTPException(429) if either limit is exceeded; otherwise
    records the hit against both windows and returns. Per-account is
    checked first so an already-blocked account never consumes global
    budget."""
    key = str(clinician_user_id)

    account_allowed, account_retry_after = _per_account_limiter.hit(
        key, INVITE_PER_ACCOUNT_LIMIT, INVITE_PER_ACCOUNT_WINDOW_SECONDS
    )
    if not account_allowed:
        _invite_logger.warning(
            "clinician_invite_rate_limited", extra={"scope": "account", "retry_after_seconds": account_retry_after}
        )
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(account_retry_after)}
        )

    global_allowed, global_retry_after = _global_limiter.hit(
        _GLOBAL_KEY, INVITE_GLOBAL_LIMIT, INVITE_GLOBAL_WINDOW_SECONDS
    )
    if not global_allowed:
        _invite_logger.warning(
            "clinician_invite_rate_limited", extra={"scope": "global", "retry_after_seconds": global_retry_after}
        )
        raise HTTPException(
            status_code=429, detail=_RATE_LIMIT_DETAIL, headers={"Retry-After": str(global_retry_after)}
        )


def reset_invite_rate_limits() -> None:
    """Test-only: clears both limiters' recorded state — same pattern as
    demo_protection.py's reset_demo_rate_limits."""
    _per_account_limiter.reset()
    _global_limiter.reset()
