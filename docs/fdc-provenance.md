# USDA FoodData Central: provenance note

Short record of what the repository itself says about where the `foods`
catalogue comes from. Nothing here was checked against USDA's website or any
other outside source; anything the repo does not establish is marked
**unverified**. This note is documentation only. It is deliberately not an
entry in `backend/app/source_licence_policy.py`, which governs PhyFoodComp
alone.

## What the catalogue is

- **Source:** USDA FoodData Central (FDC) CSV exports, three datasets:
  Foundation Foods, SR Legacy and Branded Foods (`README.md`, "Download a
  USDA FoodData Central export"; `backend/app/ingest_fdc.py` module
  docstring). FDC is the only food-composition source (`README.md`).
- **Where it is obtained:** the FDC "Download Datasets" page,
  `https://fdc.nal.usda.gov/download-datasets.html` (`README.md`,
  `ingest_fdc.py`).
- **How it is loaded:** `python -m app.ingest_fdc`. Foods without a usable
  protein value are skipped (`ingest_fdc.py`), so zero-protein FDC rows,
  such as pure oils and sugars, are not in the catalogue. A GTIN is kept
  only on the first row that claims it; later label versions of the same
  barcode are stored without one (`docs/plans/canonical-foods-plan.md`
  1.1.1).
- **How it is labelled to users:** `backend/app/routers/foods.py` maps
  `data_type` to "USDA FoodData Central — Foundation Foods / SR Legacy /
  Branded Foods".

## Licence

- The only licence statement in the repo is in
  `docs/phytate-review/PRIVATE_ARTIFACTS.md`: USDA FDC catalogue data is
  "public domain, independently obtainable from `fdc.nal.usda.gov`".
- The repo does not mention CC0 or any other named licence, and holds no
  copy of USDA's terms. **The exact licence terms are unverified.**
- No attribution or citation requirement is recorded. **Unverified.**

## Which release

- **Upstream release: unrecorded.** Neither `Food` nor `ingest_fdc.py`
  records which FDC release populated a catalogue.
  `backend/app/catalogue_manifest.py` therefore reports
  `upstream_release_version` as unrecorded unless `app.inspect_fdc_release`
  finds real evidence.
- `prompts.txt` mentions a release "dated 2025-12-18" but explicitly says
  not to rely on that without verification. **Unverified.**
- One developer machine holds FDC zips named for Foundation and Branded
  2026-04-30 and SR Legacy 2018-04 in the untracked `data/` folder. That
  shows what was downloaded locally, not what production was built from.
  **Unverified for production.**
- **What is recorded:** `catalogue_snapshot_checksum` and row count
  (`catalogue_manifest.py`), a deterministic fingerprint of
  `(id, fdc_id, name, data_type)` over the catalogue. That checksum, not a
  release label, is the drift detector the phytate stable-ID mapping
  relies on.

## What would make this a formal record

These are open, not done:

1. Record USDA's own licence wording, with the date it was read.
2. Record the release date and file checksums of each dataset at ingest
   time, for example in `import_manifests`.
3. Decide whether an attribution line belongs on the methodology page.

See open question Q8 in `docs/plans/canonical-foods-plan.md`.
