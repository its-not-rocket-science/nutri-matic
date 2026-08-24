# PhyFoodComp private artifacts (PROMPT 9, 2026-08-24)

## What changed and why

`source_licence_policy.py` records, for the `phyfoodcomp_1_0` source, right
now:

```
redistribution_permitted=False
export_permitted=False
```

Fourteen files tracked in this (public) repository under `docs/phytate-review/`
contained verbatim PhyFoodComp source food descriptions and the exact reported
phytate values — not just reviewer decisions or code. That is present-tense
public redistribution against the project's own recorded policy, independent
of and more urgent than the still-pending question of commercial-use
permission. This directory's `.gitignore` entries and this document are the
fix: those 14 files are no longer tracked in git (as of the commit that added
this file), though they remain present on disk for anyone who already has
them checked out locally or who is supplied them directly by Paul.

Only the *workbook's own reported values and descriptions* triggered removal.
Files that carry only USDA FDC catalogue data (public domain, independently
obtainable from `fdc.nal.usda.gov`) or reviewer/resolver decision metadata
(a row_identifier and a chosen `fdc_id`, with no original source text or
measured value) stay public — see the inventory below.

**No git history was rewritten.** Every one of these files' full contents
still exists in this repository's history, in every commit before the one
that removed them from tracking. That is a real, separate exposure this PR
does not attempt to fix — see "What this PR does *not* do" below.

## Inventory

| File | Contains PhyFoodComp source text/values? | Runtime dependency | Independently obtainable? |
|---|---|---|---|
| `final_approved_mapping.csv` | Yes — `food_description`, `compound_fraction`, `value` per row | Yes — `app.resolve_phytate_stable_ids`'s default `--mapping-csv` input | No — derived from the licensed workbook |
| `stable_id_mapping.csv` | Yes — same three columns, plus resolved `fdc_id`/`food_id` | Yes — `app.import_reviewed_phytate_mappings`'s default `--stable-id-mapping` input | No |
| `review_1_ambiguous.csv` | Yes | Yes — one of the seven signed review files `app.import_reviewed_phytate_mappings` reads by default | No |
| `review_2_no_candidate.csv` | Yes | Yes | No |
| `review_3_branded_low_confidence.csv` | Yes | Yes | No |
| `review_4_special_cases.csv` | Yes | Yes | No |
| `review_5_infant_flour_cluster.csv` | Yes | Yes | No |
| `review_6_accepted_sample.csv` | Yes | Yes | No |
| `review_6b_accepted_remainder.csv` | Yes | Yes | No |
| `pre-3b-baseline/*.csv` (4 files) | Yes | No — superseded draft snapshots, predate Prompt 3b, not read by any code path | No |
| `prompt3b_bug_evidence_and_fixtures.csv` | Yes | No — historical bug-investigation evidence, referenced only in test docstrings/comments, never read by code | No |
| `stable_id_exceptions.csv` | **No** — `row_identifier, reason, approved_fdc_food, data_type, detail`; `approved_fdc_food` here is the *FDC candidate name*, not the original source description | Yes — resolver output | Effectively yes (FDC candidate names only) |
| `stable_id_exceptions_resolved.csv` | **No** — `row_identifier, chosen_fdc_id, resolver_note`; notes reference only FDC-side nutrient/GTIN data | Yes — resolver override input | Yes (FDC data only) |
| `stable_id_duplicates_still_needing_review.csv` | **No** — FDC candidate names, GTINs, and FDC nutrient values only | No — audit trail from manual duplicate resolution | Yes (FDC data only) |
| `fdc_catalogue_manifest.json` | **No** — a checksum, row count, and dates | Yes — catalogue drift detection | N/A — a fingerprint, not source data |
| `check_consistency.py`, `export_*.py`, `review_helper.py` | **No** — code | Yes (tooling) | N/A |
| `phytate-review-protocol.txt` | **No** — procedural instructions | No | N/A |

## How an authorised operator supplies the real files

No code change was needed for this. Every tool that reads these files
already accepts an explicit path, and defaults to the same
`docs/phytate-review/` location the files used to live in when tracked:

```
python -m app.resolve_phytate_stable_ids --mapping-csv /path/to/final_approved_mapping.csv ...
python -m app.import_reviewed_phytate_mappings --review-dir /path/to/review/dir --stable-id-mapping /path/to/stable_id_mapping.csv ...
```

If you already have these 14 files checked out locally from before this
change, they remain exactly where they were — `git rm --cached` does not
touch the working tree, only the index — and `.gitignore` now prevents
`git add` from re-tracking them by accident. If you are setting up a fresh
clone and need to run the resolver or reviewed importer against the real
data, Paul supplies these files directly, out of band from git.

## What this PR does *not* do

- **Does not rewrite git history.** The full content of all 14 files is
  still recoverable from any commit before this one. That is a distinct,
  larger decision (force-push, coordination with anyone who has cloned or
  forked the repo, cannot guarantee removal from third-party caches) —
  see prompts.txt's OPTIONAL PROMPT 15. Not run without Paul's explicit
  decision.
- **Does not rebuild the CI regeneration/consistency check.** That check
  needed the real files present in a public CI runner to do its job; making
  it work against a synthetic fixture instead (so ordinary public CI needs
  neither the real data nor a secret) is prompts.txt PROMPT 12's explicit
  scope, not this change's.
- **Does not change `redistribution_permitted`/`export_permitted`.** Those
  stay `False` until Paul records FAO's actual written terms.
