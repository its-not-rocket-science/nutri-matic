"""Liveness/readiness endpoints — operational-hardening prompt 5.

Unauthenticated (a load balancer/orchestrator's health check has no
credentials to send) and deliberately minimal — neither endpoint ever
returns anything beyond a status word and, on failure, a short
human-readable reason. No stack trace, no database URL, no internal
identifiers: see `test_health.py::test_health_endpoints_do_not_leak_
secrets` for what this is checked against directly.

Both dependencies below (`get_db`, `get_database_url`) are the same
kind of override point every other router in this app already uses
(`app.dependency_overrides[...]` in tests) — deliberately, so this
endpoint's failure modes (DB unreachable, schema behind head) are
testable the normal way rather than needing to patch module-level
globals."""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import DATABASE_URL, get_db
from ..monitoring import alembic_head_and_current
from ..redis_rate_limit import REDIS_URL, RateLimitStoreError, get_redis_rate_limiter

router = APIRouter(prefix="/api", tags=["health"])
_logger = logging.getLogger("app.health")

# Public-launch hardening prompt 6 item 2 ("database connection
# exhaustion/latency"). A plain `SELECT 1` taking this long is itself a
# real signal something's wrong (pool exhaustion, a slow/overloaded
# database) — an orchestrator polling /api/ready every few seconds gives
# this a natural, cheap sampling cadence with no extra machinery needed.
SLOW_READINESS_CHECK_THRESHOLD_MS = 500


def get_database_url() -> str:
    return DATABASE_URL


@router.get("/health")
def liveness():
    """Process is up and serving requests. Never touches the database —
    that's what /api/ready is for. A load balancer should stop routing
    new traffic here if this ever fails to respond at all, but a failure
    of this specific check almost never happens on its own (the process
    either serves HTTP or it doesn't). Pre-existing endpoint (moved here
    from main.py for operational-hardening prompt 5, same path/response
    shape — not a breaking change for anything already polling it)."""
    return {"status": "ok"}


@router.get("/ready")
def readiness(db: Session = Depends(get_db), database_url: str = Depends(get_database_url)):
    """Fit to actually serve real requests: the database is reachable,
    and the schema is at the Alembic head every currently-deployed
    version of the code expects. The second check is what catches "the
    container started but the migration step failed or was skipped" —
    without it, a container could report healthy while every request
    that touches a table/column a pending migration was supposed to add
    fails with a real database error."""
    started_at = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {type(exc).__name__}")
    duration_ms = (time.monotonic() - started_at) * 1000
    if duration_ms >= SLOW_READINESS_CHECK_THRESHOLD_MS:
        # ERROR, not WARNING: init_monitoring()'s LoggingIntegration only
        # turns ERROR+ into a Sentry event (WARNING is breadcrumb-only) —
        # this signal needs to actually alert, not sit invisible until
        # some unrelated exception happens to attach it as context.
        _logger.error("slow_readiness_db_check", extra={"duration_ms": round(duration_ms, 1)})

    current, head = alembic_head_and_current(database_url)
    if current != head:
        raise HTTPException(
            status_code=503,
            detail=f"database schema not at migration head (current={current!r}, head={head!r})",
        )

    # Operational-hardening prompt 2: only checked when REDIS_URL is
    # actually configured — a dev/CI environment with no Redis at all is
    # a legitimate, explicitly-selected local/test fallback (see
    # redis_rate_limit.py's own docstring and validate_rate_limit_config,
    # which already refuses to start at all if APP_ENV=production and
    # REDIS_URL is unset), not something readiness should ever fail for.
    # Once configured, an unreachable store must fail readiness — the
    # rate limiter protecting POST /api/auth/demo silently degrading has
    # the same "unlimited account creation" consequence a database
    # outage has for everything else this endpoint checks.
    if REDIS_URL:
        redis_limiter = get_redis_rate_limiter()
        try:
            redis_limiter.ping()
        except RateLimitStoreError as exc:
            # PR review: redis-py connection errors commonly embed the
            # internal host/port in their message — str(exc) on this
            # unauthenticated endpoint would leak that to any caller.
            # Same sanitised convention the database check above already
            # uses (type name only in the response); the full detail
            # still reaches operators, via this log line.
            _logger.error("readiness_redis_unavailable", extra={"error": str(exc)})
            raise HTTPException(status_code=503, detail=f"rate limit store unavailable: {type(exc).__name__}")

    return {"status": "ready"}
