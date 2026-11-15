"""Migration-head status for the readiness endpoint (routers/health.py)."""

from __future__ import annotations

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


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
