"""Tests for the read-only pre-stamp schema verifier — operational
hardening prompt 3 (see app/verify_pre_alembic_schema.py). Runs against
a real, disposable Postgres database, same convention and same
CI/local-skip behaviour as tests/test_migrations.py — the whole point is
verifying real schema-drift detection that SQLite couldn't exercise
(the pg_trgm extension check in particular)."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa

psycopg2 = pytest.importorskip("psycopg2")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.verify_pre_alembic_schema import main, redact_url, verify_schema  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get("DATABASE_URL", "postgresql://nutrimatic:nutrimatic@localhost:5432/nutrimatic")
TEST_DB_NAME = "nutrimatic_verify_schema_test"
BASELINE_REVISION = "aac138c38096"


def _maintenance_url() -> str:
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))


def _test_db_url() -> str:
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{TEST_DB_NAME}", "", ""))


def _postgres_available_with_createdb() -> bool:
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
        "verify_pre_alembic_schema tests cannot run in CI: no Postgres reachable with "
        "CREATEDB privilege — check the Postgres service configuration in "
        ".github/workflows/ci.yml rather than letting these tests silently skip."
    )

pytestmark = pytest.mark.skipif(
    not _HAS_CREATEDB,
    reason="no Postgres reachable with CREATEDB privilege for schema-verifier tests",
)


def _alembic(args: list[str], db_url: str) -> None:
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"


@pytest.fixture
def baseline_db():
    """A real Postgres database with exactly the baseline schema
    applied — the "exact match" case every other test in this file
    deliberately damages one piece of."""
    conn = psycopg2.connect(_maintenance_url())
    conn.autocommit = True
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    conn.cursor().execute(f"CREATE DATABASE {TEST_DB_NAME}")
    conn.close()

    _alembic(["upgrade", BASELINE_REVISION], _test_db_url())

    yield _test_db_url()

    conn = psycopg2.connect(_maintenance_url())
    conn.autocommit = True
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    conn.close()


def test_exact_baseline_schema_passes(baseline_db):
    engine = sa.create_engine(baseline_db)
    result = verify_schema(engine)
    engine.dispose()
    assert result.issues == []
    assert result.ok is True


def test_missing_table_fails(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE recipe_tags"))
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("missing table: recipe_tags" in issue for issue in result.issues)


def test_missing_column_fails(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE users DROP COLUMN currency"))
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("users" in issue and "currency" in issue for issue in result.issues)


def test_wrong_type_fails(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE users ALTER COLUMN birth_year TYPE VARCHAR USING birth_year::varchar"))
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("birth_year" in issue and "incompatible column type" in issue for issue in result.issues)


def test_missing_unique_index_fails(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_recipes_import_slug"))
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("ix_recipes_import_slug" in issue for issue in result.issues)


def test_missing_pg_trgm_fails(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP EXTENSION pg_trgm CASCADE"))
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("pg_trgm" in issue for issue in result.issues)


def test_credentials_are_redacted():
    redacted = redact_url("postgresql://nutrimatic:supersecretpassword@localhost:5432/nutrimatic")
    assert "supersecretpassword" not in redacted
    assert "nutrimatic" in redacted  # username/db/host still shown — only the password is sensitive here
    assert "localhost:5432" in redacted


def test_main_exits_non_zero_on_failure(baseline_db):
    engine = sa.create_engine(baseline_db)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE recipe_tags"))
    engine.dispose()
    exit_code = main(["--database-url", baseline_db])
    assert exit_code != 0


def test_main_exits_zero_on_success(baseline_db):
    exit_code = main(["--database-url", baseline_db])
    assert exit_code == 0


def test_non_postgres_dialect_fails_cleanly():
    engine = sa.create_engine("sqlite:///:memory:")
    result = verify_schema(engine)
    engine.dispose()
    assert result.ok is False
    assert any("PostgreSQL" in issue for issue in result.issues)
