"""Safe, non-destructive post-deploy smoke check — public-launch
hardening prompt 6 item 6.

Checks the things a deploy can silently get wrong even when CI passed:
the frontend actually serving its public pages, static/PWA assets, and
the backend's own health/readiness — plus, only when explicitly asked
for and only when it can also clean up after itself, a real end-to-end
demo-account flow.

Read-only by default. The one write it can ever make (creating a demo
account) is opt-in (`--include-demo-flow`) and only proceeds if a
database connection is available to immediately delete exactly that one
account afterward — the explicit "must not create unbounded retained
demo data" requirement. No database access, no demo check: the script
skips it and says so, rather than creating an account it can't clean up.

Usage:
    python -m app.smoke_check --backend-url https://api.nutri-matic.uk --frontend-url https://nutri-matic.uk
    python -m app.smoke_check --backend-url ... --frontend-url ... --include-demo-flow
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _get(client: httpx.Client, url: str) -> httpx.Response | "_FailedResponse":
    try:
        return client.get(url, timeout=10.0)
    except httpx.HTTPError as exc:
        return _FailedResponse(exc)


class _FailedResponse:
    """Stands in for a response when the request itself failed (DNS,
    connection refused, timeout) — keeps the check functions below from
    needing a separate try/except at every call site."""

    status_code = None

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    @property
    def text(self) -> str:
        return f"request failed: {type(self.exc).__name__}: {self.exc}"


def check_backend_health(client: httpx.Client, backend_url: str) -> CheckResult:
    res = _get(client, f"{backend_url}/api/health")
    ok = res.status_code == 200
    return CheckResult("backend_health", ok, "200 OK" if ok else f"status={res.status_code} body={res.text[:200]}")


def check_backend_ready(client: httpx.Client, backend_url: str) -> CheckResult:
    res = _get(client, f"{backend_url}/api/ready")
    ok = res.status_code == 200
    return CheckResult("backend_ready", ok, "200 ready" if ok else f"status={res.status_code} body={res.text[:200]}")


def check_frontend_page(client: httpx.Client, frontend_url: str, path: str) -> CheckResult:
    res = _get(client, f"{frontend_url}{path}")
    ok = res.status_code == 200
    return CheckResult(f"frontend_{path or 'home'}", ok, "200 OK" if ok else f"status={res.status_code}")


def check_frontend_static_asset(client: httpx.Client, frontend_url: str, path: str, must_contain: str | None = None) -> CheckResult:
    res = _get(client, f"{frontend_url}{path}")
    if res.status_code != 200:
        return CheckResult(f"frontend_static_{path}", False, f"status={res.status_code}")
    if must_contain and must_contain not in res.text:
        return CheckResult(f"frontend_static_{path}", False, f"200 OK but missing expected content {must_contain!r}")
    return CheckResult(f"frontend_static_{path}", True, "200 OK")


def _decode_user_id_from_token(token: str) -> int | None:
    """Reads the `sub` claim directly off the just-issued token —
    informational only, no signature verification needed: this is the
    smoke check reading its own freshly-received token to identify the
    account for cleanup, not trusting untrusted external input. Doing
    this instead of relying on a follow-up `/me` call means the account
    can still be identified and deleted even if `/me` itself times out
    or errors (caught by review: cleanup must not depend on the
    verification calls succeeding)."""
    import jwt as pyjwt

    try:
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return int(payload["sub"])
    except Exception:  # noqa: BLE001 — any malformed/unexpected token shape just means "can't identify it"
        return None


def check_demo_flow(client: httpx.Client, backend_url: str, database_url: str | None) -> CheckResult:
    """Creates one real demo account, verifies the auth/me/profiles flow
    end to end, then deletes exactly that account — never left behind.
    Skipped (not failed) if no database connection is available to
    guarantee the cleanup.

    Cleanup is attempted for every path once an account is known to have
    been created (a `finally` block, not just the happy path) and its
    outcome — including a refused/failed deletion — is folded into the
    overall pass/fail result, not silently reported as a passing check
    with a failure detail buried in the text (caught by review)."""
    if not database_url:
        return CheckResult(
            "demo_flow", True,
            "skipped — no database_url given, so cleanup couldn't be guaranteed (see module docstring)",
        )

    try:
        res = client.post(f"{backend_url}/api/auth/demo", timeout=10.0)
    except httpx.HTTPError as exc:
        return CheckResult("demo_flow", False, f"POST /api/auth/demo failed: {exc}")

    if res.status_code != 201:
        return CheckResult("demo_flow", False, f"POST /api/auth/demo returned {res.status_code}: {res.text[:200]}")

    try:
        token = res.json().get("access_token")
    except ValueError as exc:
        return CheckResult("demo_flow", False, f"POST /api/auth/demo returned invalid JSON: {exc}")

    user_id = _decode_user_id_from_token(token) if token else None
    headers = {"Authorization": f"Bearer {token}"}
    me_status: int | str = "not attempted"
    profiles_status: int | str = "not attempted"
    cleanup_detail = "no cleanup attempted (couldn't decode a user id from the returned token)"

    try:
        try:
            me_res = client.get(f"{backend_url}/api/auth/me", headers=headers, timeout=10.0)
            me_status = me_res.status_code
        except httpx.HTTPError as exc:
            me_status = f"request failed: {exc}"

        try:
            profiles_res = client.get(f"{backend_url}/api/profiles", headers=headers, timeout=10.0)
            profiles_status = profiles_res.status_code
        except httpx.HTTPError as exc:
            profiles_status = f"request failed: {exc}"
    finally:
        # Cleanup runs whenever an id was decoded, regardless of how the
        # verification calls above went — a timeout on /me must not
        # leave the account behind.
        if user_id is not None:
            cleanup_detail = _cleanup_demo_account(database_url, user_id)

    ok = me_status == 200 and profiles_status == 200 and cleanup_detail.startswith("deleted")
    detail = (
        f"created user_id={user_id}, /me status={me_status}, "
        f"/profiles status={profiles_status}; cleanup: {cleanup_detail}"
    )
    return CheckResult("demo_flow", ok, detail)


def _cleanup_demo_account(database_url: str, user_id: int) -> str:
    """Deletes exactly the one account this check just created, reusing
    demo_purge's own dependent-row deletion — the same logic prompt 2's
    scheduled purge uses, just targeted at a single known-fresh account
    instead of "everything expired".

    Verifies the row is actually a demo account (`is_demo` true and the
    email under demo_data.py's reserved `DEMO_EMAIL_DOMAIN`) before ever
    deleting anything — `_delete_batch` itself doesn't filter on
    `is_demo`, so if `--database-url` were ever pointed at a different
    environment than `--backend-url`, the numeric id returned could
    coincidentally belong to an unrelated real account there; refusing
    to delete anything that doesn't look like a demo account is what
    keeps that mismatch from being destructive (caught by review)."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from .demo_data import DEMO_EMAIL_DOMAIN
    from .demo_purge import _delete_batch
    from .models import User

    engine = sa.create_engine(database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user is None:
            return f"FAILED to delete user_id={user_id}: no such user in this database"
        if not user.is_demo or not user.email.endswith(f"@{DEMO_EMAIL_DOMAIN}"):
            return (
                f"REFUSED to delete user_id={user_id}: does not look like a demo account "
                f"(is_demo={user.is_demo}, email={user.email!r}) — --database-url may point "
                "at the wrong environment"
            )
        _delete_batch(db, [user_id])
        db.commit()
        return f"deleted user_id={user_id}"
    except Exception as exc:  # noqa: BLE001 — report, don't crash the whole smoke check over cleanup
        db.rollback()
        return f"FAILED to delete user_id={user_id}: {exc}"
    finally:
        db.close()
        engine.dispose()


def run_smoke_check(
    backend_url: str, frontend_url: str, *, include_demo_flow: bool = False, database_url: str | None = None,
) -> list[CheckResult]:
    with httpx.Client() as client:
        results = [
            check_backend_health(client, backend_url),
            check_backend_ready(client, backend_url),
            check_frontend_page(client, frontend_url, ""),
            check_frontend_page(client, frontend_url, "/about"),
            check_frontend_page(client, frontend_url, "/methodology"),
            check_frontend_static_asset(client, frontend_url, "/robots.txt", must_contain="Sitemap:"),
            check_frontend_static_asset(client, frontend_url, "/sitemap.xml", must_contain="<urlset"),
            check_frontend_static_asset(client, frontend_url, "/manifest.webmanifest"),
        ]
        if include_demo_flow:
            results.append(check_demo_flow(client, backend_url, database_url))
    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend-url", required=True, help="e.g. https://api.nutri-matic.uk (no trailing slash)")
    parser.add_argument("--frontend-url", required=True, help="e.g. https://nutri-matic.uk (no trailing slash)")
    parser.add_argument(
        "--include-demo-flow", action="store_true",
        help="Also create-and-immediately-delete one real demo account. Requires --database-url.",
    )
    parser.add_argument(
        "--database-url", default=None,
        help="Required only with --include-demo-flow, to guarantee the created account is cleaned up.",
    )
    args = parser.parse_args(argv)

    results = run_smoke_check(
        args.backend_url.rstrip("/"), args.frontend_url.rstrip("/"),
        include_demo_flow=args.include_demo_flow, database_url=args.database_url,
    )

    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'}  {r.name:30s} {r.detail}")

    if any(not r.ok for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
