"""Production monitoring/alerting — operational-hardening prompt 5.

No-op unless `SENTRY_DSN` is set — missing monitoring credentials must
never break local development or CI (see `tests/test_monitoring.py`'s
"missing credentials do not break local development" case), so
`init_monitoring()` is always safe to call unconditionally at startup.

Application code never imports `sentry_sdk` directly anywhere else in
this codebase — it logs, at the appropriate level, to the standard
`logging` module's `app.*` loggers (see `routers/recommendations.py`'s
`_log_substitution_outcome`/`_log_disabled_response` for the two cases
this prompt specifically asks to capture: substitution apply outcomes
and disabled-recommendation responses by reason code). Sentry's own
`LoggingIntegration`, configured below, is what turns a `WARNING`+ log
record into a captured event when monitoring is actually active — this
keeps business logic decoupled from which (if any) monitoring vendor is
configured, matching how `APP_ENV`/`JWT_SECRET` are read elsewhere in
this app (see `app/auth.py`)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Fields never sent to Sentry, in any event — request headers/cookies,
# request body keys, or `extra=` logging context matching these
# (case-insensitive). Deliberately broad rather than an exact-match
# allowlist: a new sensitive field added elsewhere in the app is scrubbed
# by default here rather than silently leaking until someone remembers
# to extend a narrow allowlist.
_SENSITIVE_KEY_SUBSTRINGS = (
    "authorization", "token", "password", "secret", "jwt", "cookie",
    "note", "medical", "dietary_note",
)

# Public-launch hardening prompt 6 — this app's user-facing identifier
# is an email address (there's no separate username), and the prompt
# explicitly names emails alongside tokens/passwords/diary contents as
# never to leak into telemetry. A key-name check alone (as used above)
# isn't enough here: an email can show up under any key (login/register
# bodies, a future "shared with" field, a free-text field that happens
# to contain one) — matched and redacted by *pattern*, wherever it
# appears in a string value, rather than only when the key itself looks
# email-shaped. Operational-hardening prompt 5's own test suite
# previously asserted email was deliberately left unscrubbed; that
# policy is superseded here by this prompt's explicit instruction.
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_SUBSTRINGS)


def _redact_database_url(value: str) -> str:
    """Same redaction `verify_pre_alembic_schema.redact_url` does —
    duplicated rather than imported to keep this module import-light and
    dependency-free of the rest of the app (it's called from `main.py`
    before other app modules are necessarily safe to import)."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(value)
    if parts.password is None:
        return value
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _redact_emails(value: str) -> str:
    return _EMAIL_PATTERN.sub("[redacted-email]", value)


def _scrub_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "[Scrubbed]"
    if isinstance(value, str) and "DATABASE_URL" in key.upper():
        return _redact_database_url(value)
    if isinstance(value, dict):
        return _scrub_mapping(value)
    if isinstance(value, list):
        return [_scrub_value(key, item) for item in value]
    if isinstance(value, str):
        return _redact_emails(value)
    return value


def _scrub_mapping(mapping: dict) -> dict:
    return {k: _scrub_value(k, v) for k, v in mapping.items()}


def scrub_event(event: dict, hint: dict) -> dict:  # noqa: ARG001 — hint required by sentry_sdk's before_send signature
    """Sentry's `before_send` hook — never sends access tokens, JWTs,
    passwords, secrets, cookies, full database URLs, or anything under a
    key that looks like a medical/dietary free-text note. Applied to
    request headers, request body/query data, and any structured
    `extra=`/breadcrumb data attached to a log record."""
    request = event.get("request")
    if request:
        if "headers" in request:
            request["headers"] = _scrub_mapping(request["headers"])
        if "cookies" in request:
            request["cookies"] = "[Scrubbed]"
        data = request.get("data")
        if isinstance(data, dict):
            request["data"] = _scrub_mapping(data)

    if "extra" in event and isinstance(event["extra"], dict):
        event["extra"] = _scrub_mapping(event["extra"])

    for breadcrumb in event.get("breadcrumbs", {}).get("values", []) if event.get("breadcrumbs") else []:
        if isinstance(breadcrumb.get("data"), dict):
            breadcrumb["data"] = _scrub_mapping(breadcrumb["data"])

    return event


_initialized = False


def is_initialized() -> bool:
    return _initialized


def init_monitoring() -> bool:
    """Call once at app startup. Returns True if monitoring actually
    initialised (SENTRY_DSN was set), False if it was a no-op — callers
    that want to know (tests, mainly) can check this rather than
    reaching into sentry_sdk's own internals."""
    global _initialized
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        _initialized = False
        return False

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("APP_ENV", "development"),
        release=os.environ.get("RELEASE_VERSION"),
        # WARNING+ log records become breadcrumbs; ERROR+ become events —
        # this is what turns the plain `logging` calls throughout the app
        # (recommendation endpoint outcomes, disabled-reason responses)
        # into Sentry data without any sentry_sdk-specific call at those
        # sites.
        #
        # An *uncaught* exception (an actual unhandled 500, not a logged
        # WARNING/ERROR) is captured separately — sentry_sdk's
        # `auto_enabling_integrations` (the default; not disabled here)
        # detects that `starlette`/`fastapi` are installed and enables
        # `StarletteIntegration`/`FastApiIntegration` automatically.
        # Confirmed directly (not assumed): both appear in sentry_sdk's
        # own `_AUTO_ENABLING_INTEGRATIONS` list, and
        # `test_captures_uncaught_exceptions_via_the_auto_enabled_fastapi_
        # integration` below raises a real unhandled exception through a
        # live app and asserts it reaches `before_send`.
        integrations=[LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)],
        before_send=scrub_event,
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        # Explicit, not just relying on the SDK's own default (which is
        # also False): never attach IP address/user context Sentry would
        # otherwise infer from the request, on top of this module's own
        # scrub_event redaction.
        send_default_pii=False,
    )
    _initialized = True
    return True


def validate_monitoring_config() -> None:
    """Operational-hardening prompt 4, requirement 1: production must not
    silently run with no error monitoring at all. Call once, right after
    `init_monitoring()` (see main.py) — a no-op when monitoring actually
    initialised.

    Deliberately a loud WARN, not the hard-fail-at-import pattern
    `auth.py`'s `_resolve_jwt_secret`/`redis_rate_limit.
    validate_rate_limit_config` use for `JWT_SECRET`/`REDIS_URL`: those
    guard security and rate-limit *integrity*, where starting anyway
    would be actively unsafe. Missing observability is a real
    operational risk — but making the whole app's availability depend on
    a third-party monitoring vendor being configured would itself be a
    new production risk this app doesn't need; "can't see errors" is a
    materially different failure mode than "forges auth tokens" or
    "unlimited account creation". `requirement 1`'s own wording offers
    "warn loudly OR fail" — this is the warn-loudly half.

    The log call itself reaches container/CI stderr even with no
    handler configured anywhere in this app (confirmed, not assumed —
    see `test_warns_via_pythons_own_last_resort_handler_with_no_
    configured_handler` in tests/test_monitoring.py): Python's logging
    module falls back to printing WARNING+ records to stderr
    (`logging.lastResort`) when no handler exists on the logger or any
    ancestor up to root, which is exactly this app's situation before
    `init_monitoring()` ever calls `sentry_sdk.init()` — so this is
    visible in plain container logs regardless of whether Sentry itself
    is reachable, not just useful once monitoring is already working."""
    if is_initialized():
        return
    if os.environ.get("APP_ENV", "development") != "production":
        return
    logging.getLogger("app.monitoring").error(
        "monitoring_not_configured",
        extra={
            "detail": (
                "APP_ENV=production but SENTRY_DSN is unset — starting anyway, but running "
                "with no error monitoring at all. Set SENTRY_DSN. See docs/monitoring.md."
            )
        },
    )


def alembic_head_and_current(database_url: str) -> tuple[str | None, str | None]:
    """Returns (current_revision, head_revision) for the readiness
    endpoint's migration-head check. `current` is read directly from the
    `alembic_version` table (a plain SELECT — no Alembic machinery
    needed for this half); `head` is resolved from the migration scripts
    on disk via Alembic's own ScriptDirectory, the same source of truth
    `alembic current`/`alembic heads` use."""
    import sqlalchemy as sa
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    engine = sa.create_engine(database_url)
    try:
        with engine.connect() as conn:
            try:
                current = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
            except sa.exc.ProgrammingError:
                current = None  # alembic_version doesn't exist yet — never migrated
    finally:
        engine.dispose()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()

    return current, head
