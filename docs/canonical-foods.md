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
| Loads in production | Alembic data migrations that pin the file's sha256 (`348add18915d`, `18067652e674`, then `cf2908ff260e`) |
| Read by | `search.search_foods_by_name_hits`, tier 1 (below) |

## Changing the file

1. **Edit the CSV as UTF-8 text**, not in Excel. A spreadsheet round trip
   garbles accents ("purÃ©e"), adds a byte-order mark and rewrites dates as
   28/11/2026. The validator rejects all three. There is one row per alias.
   Keep the canonical columns identical on every row of the same
   `canonical_key`.
   - `anchor_fdc_name` is the anchor row's exact FDC name, so a reviewer can
     see what the id is. The load fails if the catalogue's name differs, and
     also if the anchor reports no energy.
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
   - Add `--allow-unsigned` to either to preview a draft whose rows still say
     `PENDING`. A real `load` refuses it.
   - `tests/test_canonical_search.py` searches every alias in the file over
     the golden mini catalogue. A new anchor must be added to
     `tests/fixtures/search_golden_catalogue.json` (FDC id, type and name
     only).
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
  database). After ingesting into a fresh database (`app.ingest_fdc` also
  inserts the protein-free staples the file anchors on), run
  `python -m app.canonical_foods load` (README step 2b).
- It never writes `foods`, so the catalogue checksum does not change. It never
  reads or writes phytate data.
- Diary entries, recipes and plans keep their own `food_id`. Nothing is
  re-pointed retroactively.

## How search uses it (tier 1)

- A query that equals an alias, in the request locale or `*`, returns that
  canonical's anchor row first. The last word may be singular or plural
  ("chickpea" finds "chickpeas"). Anything else is not a tier-1 match.
- The concept's other active preparation variants follow as siblings
  ("chickpeas" → tinned, boiled, dried). Within a concept the matched
  canonicals come first, then the preparation tie-break: the state the query
  names, else the en-GB default (tinned chickpeas, dry lentils, frozen
  peas, ...). `tests/test_canonical_search.py::MULTI_STATE_FIRST` records
  the expected first state for every alias that covers several states; a
  new one fails CI until its default is decided.
- An `ambiguous` alias ("milk", "pepper") lists each concept, in concept-key
  order.
- The ranked token search fills the rest of the list without repeating an
  anchor. With empty canonical tables search behaves exactly as before.
- A result shows the canonical's display name, then "USDA SR Legacy: <FDC
  row name>", and the alias note if there is one. What gets logged is the
  anchor's own `food_id`.

## Not yet

- `canonical_typical_values` stays empty: PR 5 (typical values) is deferred
  (plan Q4). A concept with no SR Legacy or Foundation row has no canonical.
- Sugar, oils, salt and other protein-free staples are anchorable since the
  SR staples migration (`5085bc12af5a`, `backend/app/fdc_staples.py`).
