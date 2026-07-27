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


def check_demo_flow(client: httpx.Client, backend_url: str, database_url: str | None) -> CheckResult:
    """Creates one real demo account, verifies the auth/me/profiles flow
    end to end, then deletes exactly that account — never left behind.
    Skipped (not failed) if no database connection is available to
    guarantee the cleanup."""
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
    token = res.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}

    me_res = client.get(f"{backend_url}/api/auth/me", headers=headers, timeout=10.0)
    profiles_res = client.get(f"{backend_url}/api/profiles", headers=headers, timeout=10.0)
    ok = me_res.status_code == 200 and profiles_res.status_code == 200
    user_id = me_res.json().get("id") if me_res.status_code == 200 else None

    cleanup_detail = "no cleanup attempted (couldn't identify the created account)"
    if user_id is not None:
        cleanup_detail = _cleanup_demo_account(database_url, user_id)

    detail = (
        f"created user_id={user_id}, /me status={me_res.status_code}, "
        f"/profiles status={profiles_res.status_code}; cleanup: {cleanup_detail}"
    )
    return CheckResult("demo_flow", ok, detail)


def _cleanup_demo_account(database_url: str, user_id: int) -> str:
    """Deletes exactly the one account this check just created, reusing
    demo_purge's own dependent-row deletion — the same logic prompt 2's
    scheduled purge uses, just targeted at a single known-fresh account
    instead of "everything expired"."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from .demo_purge import _delete_batch

    engine = sa.create_engine(database_url)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
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
