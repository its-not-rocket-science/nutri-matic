"""Compares what app.models/app.database's SQLAlchemy metadata expects
against what's actually live in the connected database (DATABASE_URL).
Read-only — issues no DDL.

Used by the migration-rehearsal step in .github/workflows/deploy.yml, and
safe to run manually against any environment:

    DATABASE_URL=... python check_schema_drift.py

Exits 0 with no drift, exits 1 (via assertion-style failure) if drift is
found, so it can gate CI.
"""

import sys

from sqlalchemy import inspect

from app.database import engine, Base
from app import models  # noqa: F401  (populates Base.metadata)

inspector = inspect(engine)
live_tables = set(inspector.get_table_names()) - {"alembic_version"}
model_tables = set(Base.metadata.tables.keys())

missing_tables = model_tables - live_tables
extra_tables = live_tables - model_tables

any_drift = False

print("=== Tables in models but not in live DB ===")
if missing_tables:
    any_drift = True
print(sorted(missing_tables) or "(none)")

print("\n=== Tables in live DB but not in models ===")
if extra_tables:
    any_drift = True
print(sorted(extra_tables) or "(none)")

print("\n=== Column-level drift per shared table ===")
for table_name in sorted(model_tables & live_tables):
    model_cols = {c.name: c for c in Base.metadata.tables[table_name].columns}
    live_cols = {c["name"]: c for c in inspector.get_columns(table_name)}

    missing_cols = set(model_cols) - set(live_cols)
    extra_cols = set(live_cols) - set(model_cols)

    nullability_mismatches = []
    for col_name in set(model_cols) & set(live_cols):
        model_nullable = model_cols[col_name].nullable
        live_nullable = live_cols[col_name]["nullable"]
        if model_nullable != live_nullable:
            nullability_mismatches.append(
                f"{col_name} (model nullable={model_nullable}, live nullable={live_nullable})"
            )

    if missing_cols or extra_cols or nullability_mismatches:
        any_drift = True
        print(f"\n-- {table_name} --")
        if missing_cols:
            print(f"  missing columns (in model, not in DB): {sorted(missing_cols)}")
        if extra_cols:
            print(f"  extra columns (in DB, not in model):   {sorted(extra_cols)}")
        if nullability_mismatches:
            print(f"  nullability mismatches: {nullability_mismatches}")

if not any_drift:
    print("(no column-level drift found)")
else:
    print("\nSCHEMA DRIFT DETECTED — see above.")
    sys.exit(1)
