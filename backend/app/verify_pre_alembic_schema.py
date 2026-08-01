"""Read-only pre-stamp schema verifier — production-hardening (operational)
prompt 3.

`alembic stamp aac138c38096` records that a database is already at the
baseline revision without checking anything — it just writes a row into
`alembic_version`. A database that's missing a table, column, index, or
the `pg_trgm` extension (because a historical manual migration from
`DEPLOYMENT.md`'s frozen list was never actually run against it, or was
run against the wrong database) would get stamped anyway, and every
migration after the baseline would then run against a schema quietly
different from what the baseline claims.

This tool compares a live, connected database against the *exact* DDL
`aac138c38096`'s own `upgrade()` would emit — not a hand-maintained
second copy of the schema that could drift out of sync with the real
migration, but the real migration's own code, run against a recording
stand-in for Alembic's `op` instead of a real connection. If the
baseline migration is ever edited, this verifier's expectations change
with it automatically.

Usage:
    python -m app.verify_pre_alembic_schema
    python -m app.verify_pre_alembic_schema --database-url postgresql://...

Exit code 0 means PASS (safe to stamp); non-zero means FAIL (do not
stamp) or a usage/connection error. Never modifies the target database —
every check is read-only reflection (`sqlalchemy.inspect`) or a plain
SELECT against `pg_catalog`/`information_schema`. PostgreSQL only: this
mirrors what production actually runs, and reflecting against SQLite
would let dialect-specific gaps (the `pg_trgm` extension in particular)
pass silently — see `tests/test_verify_pre_alembic_schema.py`, which
runs this against a real, disposable Postgres for the same reason
`tests/test_migrations.py` does.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from importlib import import_module
from urllib.parse import urlsplit, urlunsplit

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

BASELINE_REVISION = "aac138c38096"
BASELINE_MODULE = "migrations.versions.aac138c38096_baseline"

# (table, column) pairs where a *later*, real Alembic migration
# deliberately relaxed a NOT NULL constraint the baseline originally
# defined — found live in production: migration 096f80b058ab
# (add_clinician_invite_by_email) made clinician_client_links.
# client_user_id nullable on purpose (an unregistered invite has no user
# yet), already rehearsed and deployed successfully, but this verifier's
# baseline-vs-live comparison has no way to distinguish that from
# accidental drift — every later deploy would otherwise fail this check
# forever. Add an entry here (with the migration revision that made the
# change) whenever this happens again; never remove baseline's own
# NOT NULL check for anything not listed here, since that's still real
# protection against a database silently missing a constraint the
# baseline — and any migration that hasn't since relaxed it — assumes.
_INTENTIONALLY_RELAXED_NOT_NULL: set[tuple[str, str]] = {
    ("clinician_client_links", "client_user_id"),  # 096f80b058ab
}

# Coarse type categories — a column's real DB type (VARCHAR(255) vs
# VARCHAR vs TEXT, INTEGER vs BIGINT) varies more than matters here; what
# actually matters for "is this database safe to build on" is whether an
# integer column somehow became a string, a timestamp became a plain
# date, etc. This maps SQLAlchemy generic type classes to the coarse
# category the live-DB comparison also buckets into.
_TYPE_CATEGORY = {
    "Integer": "integer", "SmallInteger": "integer", "BigInteger": "integer",
    "String": "string", "Text": "string", "Unicode": "string", "VARCHAR": "string",
    "Float": "float", "Numeric": "float",
    "Boolean": "boolean",
    "Date": "date",
    "DateTime": "datetime",
    "JSON": "json",
}


def _type_category(sa_type) -> str:
    for cls in type(sa_type).__mro__:
        if cls.__name__ in _TYPE_CATEGORY:
            return _TYPE_CATEGORY[cls.__name__]
    return type(sa_type).__name__.lower()


@dataclass
class TableSpec:
    columns: dict[str, dict] = field(default_factory=dict)  # name -> {"category": str, "nullable": bool}
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[tuple[tuple[str, ...], str]] = field(default_factory=list)  # (cols, referred_table)
    unique_constraints: list[tuple[str, ...]] = field(default_factory=list)  # sorted column tuples
    check_constraints: set[str] = field(default_factory=set)  # names


@dataclass
class IndexSpec:
    name: str
    table: str
    unique: bool


class _RecordingOp:
    """Stands in for Alembic's `op` while running the baseline
    migration's real `upgrade()` — records what it *would* do instead of
    doing it. Never opens a connection, never touches a database.

    Each `create_table(...)` call's columns/constraints are handed to a
    real `sa.Table`, bound to one `sa.MetaData` shared across every call
    this recorder makes — never connected to a database, but real enough
    that SQLAlchemy resolves primary keys, foreign keys (including
    cross-table references, since the migration creates referenced
    tables first, same order the real DDL requires), and unique/check
    constraints correctly by itself, rather than this class
    re-implementing that resolution by hand against unbound constraint
    objects (which don't carry enough information to resolve on their
    own — column-name-only unique constraints in particular)."""

    def __init__(self):
        self.tables: dict[str, TableSpec] = {}
        self.indexes: list[IndexSpec] = []
        self.requires_pg_trgm = False
        self._metadata = sa.MetaData()

    def f(self, name: str) -> str:
        # this app's metadata defines no custom Alembic naming
        # convention (see app/database.py), so op.f() is a no-op here
        return name

    def get_bind(self):
        class _FakeDialect:
            name = "postgresql"

        class _FakeBind:
            dialect = _FakeDialect()

        return _FakeBind()

    def execute(self, sql) -> None:
        if "pg_trgm" in str(sql):
            self.requires_pg_trgm = True

    def create_table(self, name: str, *items) -> None:
        table = sa.Table(name, self._metadata, *items)
        spec = TableSpec()
        for column in table.columns:
            spec.columns[column.name] = {"category": _type_category(column.type), "nullable": bool(column.nullable)}
        spec.primary_key = sorted(c.name for c in table.primary_key.columns)
        for fk in table.foreign_keys:
            spec.foreign_keys.append(((fk.parent.name,), fk.column.table.name))
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                spec.unique_constraints.append(tuple(sorted(c.name for c in constraint.columns)))
            elif isinstance(constraint, sa.CheckConstraint) and constraint.name:
                spec.check_constraints.add(str(constraint.name))
        self.tables[name] = spec

    def create_index(self, name: str, table_name: str, columns, unique: bool = False, **kwargs) -> None:
        self.indexes.append(IndexSpec(name=name, table=table_name, unique=unique))

    def drop_index(self, *a, **kw) -> None:
        pass

    def drop_table(self, *a, **kw) -> None:
        pass

    def drop_column(self, *a, **kw) -> None:
        pass

    def add_column(self, *a, **kw) -> None:
        pass

    def alter_column(self, *a, **kw) -> None:
        pass


def _expected_schema() -> _RecordingOp:
    """Runs the baseline migration's real upgrade() against the
    recorder above — this *is* running the migration's code, just with
    every `op.*` call captured instead of executed against a database."""
    module = import_module(BASELINE_MODULE)
    recorder = _RecordingOp()
    original_op = module.op
    module.op = recorder
    try:
        module.upgrade()
    finally:
        module.op = original_op
    return recorder


def redact_url(url: str) -> str:
    """Keeps host/port/database/username (useful for confirming you're
    checking the database you think you are) — replaces only the
    password."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    netloc = parts.netloc.replace(f":{parts.password}@", ":***@")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


@dataclass
class VerificationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def verify_schema(engine: Engine) -> VerificationResult:
    """The whole check. Read-only: every call below is a reflection
    (`Inspector.get_*`) or a plain SELECT — nothing here writes to or
    alters `engine`'s database."""
    if engine.dialect.name != "postgresql":
        return VerificationResult(
            ok=False,
            issues=[
                f"unsupported dialect {engine.dialect.name!r} — this verifier only supports "
                "PostgreSQL, the production database. SQLite is used elsewhere for fast test "
                "isolation, but is deliberately not supported here: dialect-specific gaps "
                "(the pg_trgm extension in particular) can't be checked against it."
            ],
        )

    expected = _expected_schema()
    inspector = inspect(engine)
    issues: list[str] = []
    warnings: list[str] = []

    actual_tables = set(inspector.get_table_names())
    for table_name, table_spec in expected.tables.items():
        if table_name not in actual_tables:
            issues.append(f"missing table: {table_name}")
            continue

        actual_columns = {c["name"]: c for c in inspector.get_columns(table_name)}
        for col_name, col_spec in table_spec.columns.items():
            if col_name not in actual_columns:
                issues.append(f"{table_name}: missing column {col_name!r}")
                continue
            actual_col = actual_columns[col_name]
            actual_category = _type_category(actual_col["type"])
            if actual_category != col_spec["category"]:
                issues.append(
                    f"{table_name}.{col_name}: expected type category {col_spec['category']!r}, "
                    f"found {actual_category!r} ({actual_col['type']}) — incompatible column type"
                )
            # only material in the direction that matters: a column the
            # baseline requires NOT NULL but the live database allows
            # NULL on is a real data-integrity gap (application code
            # written against the baseline may not handle a NULL there).
            # The reverse (live DB is NOT NULL, baseline allows NULL)
            # is strictly safer, not a problem worth blocking a stamp
            # over.
            if (
                not col_spec["nullable"] and actual_col["nullable"]
                and (table_name, col_name) not in _INTENTIONALLY_RELAXED_NOT_NULL
            ):
                issues.append(f"{table_name}.{col_name}: expected NOT NULL, found nullable")

        actual_pk = sorted(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
        if table_spec.primary_key and actual_pk != table_spec.primary_key:
            issues.append(
                f"{table_name}: expected primary key {table_spec.primary_key}, found {actual_pk}"
            )

        actual_fks = {
            (tuple(sorted(fk["constrained_columns"])), fk["referred_table"])
            for fk in inspector.get_foreign_keys(table_name)
        }
        for expected_fk in table_spec.foreign_keys:
            if expected_fk not in actual_fks:
                issues.append(f"{table_name}: missing foreign key {expected_fk[0]} -> {expected_fk[1]}")

        actual_uniques = {
            tuple(sorted(uc["column_names"])) for uc in inspector.get_unique_constraints(table_name)
        }
        # a unique constraint can equivalently be enforced by a unique
        # index (Postgres does this internally for UNIQUE constraints
        # anyway) — check both so a schema that enforces the same
        # guarantee via CREATE UNIQUE INDEX instead of ADD CONSTRAINT
        # isn't flagged as missing something it actually has.
        actual_unique_indexes = {
            tuple(sorted(ix["column_names"]))
            for ix in inspector.get_indexes(table_name)
            if ix.get("unique")
        }
        for expected_unique in table_spec.unique_constraints:
            if expected_unique not in actual_uniques and expected_unique not in actual_unique_indexes:
                issues.append(f"{table_name}: missing unique constraint on {expected_unique}")

        try:
            actual_checks = {cc["name"] for cc in inspector.get_check_constraints(table_name)}
        except NotImplementedError:
            actual_checks = set()
        for expected_check in table_spec.check_constraints:
            if expected_check not in actual_checks:
                issues.append(f"{table_name}: missing check constraint {expected_check!r}")

    # indexes — unique ones are data-integrity-critical (FAIL); plain
    # non-unique ones are performance-only for this verifier's purposes
    # (WARN) — see the "important indexes" framing in this tool's
    # module docstring / the prompt it implements.
    for index_spec in expected.indexes:
        if index_spec.table not in actual_tables:
            continue  # already reported as a missing table above
        actual_indexes = inspector.get_indexes(index_spec.table)
        found = any(ix["name"] == index_spec.name for ix in actual_indexes)
        if not found:
            message = f"missing index {index_spec.name!r} on {index_spec.table}"
            if index_spec.unique:
                issues.append(message)
            else:
                warnings.append(message)

    if expected.requires_pg_trgm:
        with engine.connect() as conn:
            has_trgm = conn.execute(
                sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).first()
        if not has_trgm:
            issues.append("missing PostgreSQL extension: pg_trgm")

    return VerificationResult(ok=not issues, issues=issues, warnings=warnings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--database-url", default=None,
        help="Defaults to app.database.DATABASE_URL (the same env var/default the app itself uses).",
    )
    args = parser.parse_args(argv)

    database_url = args.database_url
    if database_url is None:
        from .database import DATABASE_URL as database_url  # noqa: N813

    print(f"Baseline revision checked: {BASELINE_REVISION}")
    print(f"Database: {redact_url(database_url)}")
    print()

    engine = sa.create_engine(database_url)
    try:
        result = verify_schema(engine)
    finally:
        engine.dispose()

    if result.warnings:
        print(f"{len(result.warnings)} warning(s):")
        for warning in result.warnings:
            print(f"  - {warning}")
        print()

    if result.ok:
        print("RESULT: PASS — safe to run: alembic stamp " + BASELINE_REVISION)
        return 0

    print(f"RESULT: FAIL — {len(result.issues)} issue(s), do not stamp:")
    for issue in result.issues:
        print(f"  - {issue}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
