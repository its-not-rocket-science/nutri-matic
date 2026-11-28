"""Canonical foods: a reviewed, curated layer over the FDC catalogue.

See docs/plans/canonical-foods-plan.md sections 3.1-3.5. Modules:

    csv_schema.py               parse and validate the reviewed CSV (no DB)
    loader.py                   anchor checks and the idempotent load
    canonical_foods_en_gb.csv   the reviewed file itself

Run `python -m app.canonical_foods --help`.
"""
