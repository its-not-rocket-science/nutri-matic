# Canonical foods: editing and loading

The canonical foods layer is a reviewed, curated layer over the FDC catalogue.
Its design is in `docs/plans/canonical-foods-plan.md`, sections 3.1–3.5. This
page covers the day-to-day workflow.

## Where things live

| What | Where |
|---|---|
| Reviewed file | `backend/app/canonical_foods/canonical_foods_en_gb.csv` |
| Column rules | the docstring of `backend/app/canonical_foods/csv_schema.py` |
| Loader | `backend/app/canonical_foods/loader.py` |
| Tables | `canonical_foods`, `canonical_aliases`, `canonical_members`, `canonical_typical_values` |
| Loads in production | Alembic data migrations that pin the file's sha256 (the first is `348add18915d`) |

## Changing the file

1. **Edit the CSV.** There is one row per alias. Keep the canonical columns
   identical on every row of the same `canonical_key`.
   - Anchors are FDC ids of **SR Legacy or Foundation** rows. The anchor's
     classified preparation state must equal the row's `preparation_state`;
     `python -m app.preparation_coverage_report` and `classify_preparation`
     show it.
   - Where Foundation lacks energy or folate (plan 1.3), prefer SR Legacy.
   - Never copy anything from a phytate review file.
2. **Sign off.** Put the reviewer's name in `reviewer` and the date in
   `review_date` on every changed row. A row with `PENDING` or a blank reviewer
   fails CI and is never loaded.
3. **Check:**
   - `python -m app.canonical_foods validate` checks the file and prints its
     sha256.
   - `python -m app.canonical_foods load --dry-run` also runs the anchor checks
     against your local database, then rolls back.
4. **Add a data migration.** Copy the newest `*_load_canonical_foods*`
   migration and set `CSV_SHA256` to the new value. If that migration has never
   been deployed, update its pin instead.
   `tests/test_canonical_foods.py::test_newest_data_migration_pins_the_current_file`
   fails until this is done.
5. **Merge.**
   - The deploy's migration rehearsal restores the production dump and runs
     `alembic upgrade head`, so the load is checked against the real catalogue
     before the approval gate.
   - Any problem fails the migration, and nothing is written.

## What a load does

- The load is replace-by-key and idempotent.
  - A key's fields, aliases and anchor are rewritten from the file.
  - A key that is removed from the file becomes `retired`: its aliases are
    removed and the row stays.
- It is skipped on a database with no FDC catalogue rows (CI, a fresh dev
  database).
- It never writes `foods`, so the catalogue checksum does not change. It never
  reads or writes phytate data.
- Diary entries, recipes and plans keep their own `food_id`. Nothing is
  re-pointed retroactively.

## Not yet

- Search does not read canonical tables yet; that is PR 4b.
- `canonical_typical_values` stays empty until PR 5.
