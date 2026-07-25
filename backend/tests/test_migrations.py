"""Tests for the Alembic migration chain — production-hardening prompts
1 and 2 (see docs/migrations.md). Runs against a real, throwaway Postgres
database, not SQLite: the whole point is verifying real DDL behaviour
(the pg_trgm extension, the Postgres-specific partial unique index on
robustness_results, and the actual backfill SQL) that SQLite's looser
type/constraint handling could let a real bug hide behind.

Skipped automatically if no Postgres reachable with CREATEDB privilege
is available — CI always has one (see .github/workflows/ci.yml), so
this always runs there. Locally, it targets the same DATABASE_URL the
app itself defaults to, but only ever creates/drops its own throwaway
database (never the real `nutrimatic` one), so it's safe to run against
a real local Postgres — it just self-skips if that role isn't allowed
to create databases.

Operational-hardening prompt 1's explicit acceptance criterion is
"backend migration tests execute rather than skip" — a silent skip in
CI would defeat that without anyone noticing. So the skip above is only
ever a *skip* outside CI; under CI (detected via the `CI` env var
GitHub Actions always sets) the same condition raises at collection
time instead, failing the whole run loudly. CI's own workflow also
verifies CREATEDB in a dedicated step before tests run at all (see
.github/workflows/ci.yml) — this is the second, independent guard."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg2 = pytest.importorskip("psycopg2")

BACKEND_DIR = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://nutrimatic:nutrimatic@localhost:5432/nutrimatic")
TEST_DB_NAME = "nutrimatic_migrations_test"
BASELINE_REVISION = "aac138c38096"


def _maintenance_url() -> str:
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))


def _test_db_url() -> str:
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{TEST_DB_NAME}", "", ""))


def _postgres_available_with_createdb() -> bool:
    """Not just reachable — the connecting role must also be able to
    create/drop a database, or every test here would fail on setup
    rather than skip. Some local Postgres roles (this app's own default
    `nutrimatic` role on a plain, non-Docker local install, in
    particular) are reachable but deliberately not superuser/CREATEDB —
    CI's Postgres service always grants this to its own user (the
    official postgres image makes POSTGRES_USER a superuser), so this
    always runs there regardless."""
    try:
        conn = psycopg2.connect(_maintenance_url(), connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname = current_user")
        can_create = bool(cur.fetchone()[0])
        conn.close()
        return can_create
    except Exception:
        return False


_HAS_CREATEDB = _postgres_available_with_createdb()

if not _HAS_CREATEDB and os.environ.get("CI"):
    raise RuntimeError(
        "Migration tests cannot run in CI: no Postgres reachable with CREATEDB "
        "privilege. This must never happen in CI — check the Postgres service "
        "configuration in .github/workflows/ci.yml rather than letting these "
        "tests silently skip."
    )

pytestmark = pytest.mark.skipif(
    not _HAS_CREATEDB,
    reason="no Postgres reachable with CREATEDB privilege for migration tests",
)


def _drop_and_create_test_db():
    conn = psycopg2.connect(_maintenance_url())
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    conn.close()


@pytest.fixture
def fresh_db():
    _drop_and_create_test_db()
    yield _test_db_url()
    conn = psycopg2.connect(_maintenance_url())
    conn.autocommit = True
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    conn.close()


def _alembic(args: list[str], db_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    return result


def _column_is_nullable(conn, table: str, column: str) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT is_nullable FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cur.fetchone()
    assert row is not None, f"{table}.{column} does not exist"
    return row[0]


def test_upgrade_head_from_empty_creates_full_schema(fresh_db):
    _alembic(["upgrade", "head"], fresh_db)
    conn = psycopg2.connect(fresh_db)
    assert _column_is_nullable(conn, "diary_entries", "updated_at") == "NO"
    assert _column_is_nullable(conn, "meal_plan_entries", "updated_at") == "NO"
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    assert cur.fetchone() is not None
    conn.close()


def test_downgrade_full_chain_drops_everything(fresh_db):
    _alembic(["upgrade", "head"], fresh_db)
    _alembic(["downgrade", "base"], fresh_db)
    conn = psycopg2.connect(fresh_db)
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name != 'alembic_version'"
    )
    assert cur.fetchone()[0] == 0
    conn.close()


def test_stamp_then_upgrade_on_pre_existing_schema(fresh_db):
    """Simulates a real pre-Alembic database: apply the baseline for
    real (standing in for tables create_all() built historically), wipe
    the alembic_version bookkeeping to simulate "never touched by
    Alembic", then prove the documented stamp -> upgrade workflow
    (docs/migrations.md) brings it to head correctly."""
    _alembic(["upgrade", BASELINE_REVISION], fresh_db)

    conn = psycopg2.connect(fresh_db)
    conn.autocommit = True
    conn.cursor().execute("DROP TABLE IF EXISTS alembic_version")
    conn.close()

    _alembic(["stamp", BASELINE_REVISION], fresh_db)
    _alembic(["upgrade", "head"], fresh_db)

    conn = psycopg2.connect(fresh_db)
    assert _column_is_nullable(conn, "diary_entries", "updated_at") == "NO"
    conn.close()


def test_backfill_preserves_and_fills_existing_rows(fresh_db):
    """Prompt 2: adding updated_at to a table that already has rows must
    not lose the existing rows and must leave none of them NULL once
    head is reached."""
    _alembic(["upgrade", BASELINE_REVISION], fresh_db)

    conn = psycopg2.connect(fresh_db)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (id, email, password_hash, created_at, is_pregnant, is_lactating) "
        "VALUES (1, 'a@example.com', 'x', now(), false, false)"
    )
    cur.execute("INSERT INTO foods (id, name, protein_g_per_100g, amino_acids) VALUES (1, 'Rice', 2.7, '{}')")
    cur.execute(
        "INSERT INTO diary_entries (id, user_id, entry_date, meal, food_id, quantity_g) "
        "VALUES (1, 1, '2026-01-01', 'lunch', 1, 100)"
    )
    conn.close()

    _alembic(["upgrade", "head"], fresh_db)

    conn = psycopg2.connect(fresh_db)
    cur = conn.cursor()
    cur.execute("SELECT updated_at FROM diary_entries WHERE id = 1")
    row = cur.fetchone()
    assert row is not None and row[0] is not None  # the pre-existing row survived and was backfilled
    cur.execute("SELECT count(*) FROM diary_entries WHERE updated_at IS NULL")
    assert cur.fetchone()[0] == 0
    conn.close()
