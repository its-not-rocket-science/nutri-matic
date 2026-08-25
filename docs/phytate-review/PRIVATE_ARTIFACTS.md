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

**Git history was NOT rewritten by this original PROMPT 9 change.** At the
time this section was written, every one of these files' full contents
still existed in this repository's history, in every commit before the one
that removed them from tracking — a real, separate exposure this PR did
not attempt to fix. **That has since changed: see "Historical git-history
exposure (PROMPT 15, resolved 2026-08-25)" below — history has now been
rewritten** for `main` and its affected branches, with one residual gap
(GitHub's own retained PR history) documented there.

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
| `stable_id_mapping_digest.json` (PROMPT 12) | **No** — a SHA-256 digest, row count, and schema version | No — audit/drift-detection only | N/A — a fingerprint of the real mapping's bytes, not the mapping itself; see `app.validate_stable_id_mapping` |
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

**⚠ Back up these 14 files before you pull/merge this change into an
existing clone, if that clone currently has them checked out clean (no
local edits).** `git rm --cached` only protects the working tree *in the
clone where that command was run* — the commit itself still records "this
path no longer exists in the tree", and a clean working copy has nothing
stopping git from applying that removal to disk during a normal
fast-forward pull or merge. If your local copies are already git-dirty
(modified, or already untracked from an earlier run of this same change),
git will leave them alone; if they are clean/unmodified, they will be
deleted from disk, not just from the index, the moment you update. Copy
them somewhere outside the repository first if you're not certain:

```
cp docs/phytate-review/{final_approved_mapping,stable_id_mapping,review_*,prompt3b_bug_evidence_and_fixtures}.csv /somewhere/safe/
cp -r docs/phytate-review/pre-3b-baseline /somewhere/safe/
```

After updating, `.gitignore` prevents `git add` from re-tracking these
paths by accident, and every tool that reads them already accepts an
explicit path, defaulting to the same `docs/phytate-review/` location
they used to live in when tracked:

```
python -m app.resolve_phytate_stable_ids --mapping-csv /path/to/final_approved_mapping.csv ...
python -m app.import_reviewed_phytate_mappings --review-dir /path/to/review/dir --stable-id-mapping /path/to/stable_id_mapping.csv ...
```

If you are setting up a fresh clone and need to run the resolver or
reviewed importer against the real data, Paul supplies these files
directly, out of band from git.

## Historical git-history exposure (PROMPT 15, resolved 2026-08-25)

**Git history has now been rewritten.** After Paul's explicit decision
following this document's inventory, all 14 files were purged from every
commit reachable from `main`, `fix-food-search-trigram-index-usage`, and
the three `phytate-prompt-{1,2,3}-*` branches, using `git filter-repo`
against an isolated mirror clone, verified two ways before pushing:

- **Path-based**: zero commits anywhere in the filtered history touch
  any of the 14 files' historical paths.
- **Content-based**: every blob object reachable from the affected
  branches (3,580 objects) was scanned for the same fail-closed
  fingerprint `.github/scripts/check_licensed_artifacts.py` uses (OOXML
  workbook signature, or `food_description`+`compound_fraction` in a
  file's first line). The one hit found was confirmed — by exact SHA-256
  match — to be the deliberately-synthetic, already-reviewed
  `backend/tests/fixtures/synthetic_stable_id_mapping.csv`, the same fixture
  `check_licensed_artifacts.py` already allowlists by content hash for
  PROMPT 12. Nothing else matched.
- The filtered `main`'s resulting file tree was diffed against the live
  pre-rewrite `main`'s tree and found byte-identical — the rewrite
  changed only history, not current content.

**What this did *not* achieve:** GitHub retains each merged PR's full
pre-squash commit history and diff view server-side (`refs/pull/N/head`),
independent of what `main` points to. A force-push to `refs/heads/main`
does not touch that. The 14 files were originally introduced across six
squash-merged PRs — **#41, #43, #52, #54, #55, #57** — and those PR
pages, plus `git fetch origin refs/pull/<N>/head` for any of them, still
expose the original content. A fresh `git clone` of the repo (which only
ever fetches `refs/heads/*`) is clean; the six PRs' own pages are not,
yet.

**Status: a GitHub Support request to purge cached views/backups for
those six PR numbers was filed 2026-08-25.** Resolution is now on
GitHub's side, not this repository's — update this paragraph once they
respond.

Every local clone that existed before the rewrite (including the one
this repository was developed in) needed `git fetch && git reset --hard
origin/<branch>` to pick up the new history — old and new histories are
unrelated, not a fast-forward.

## What this PR does *not* do

- **Does not rebuild the CI regeneration/consistency check.** That check
  needed the real files present in a public CI runner to do its job; making
  it work against a synthetic fixture instead (so ordinary public CI needs
  neither the real data nor a secret) is prompts.txt PROMPT 12's explicit
  scope, not this change's.
- **Does not change `redistribution_permitted`/`export_permitted`.** Those
  stay `False` until Paul records FAO's actual written terms.
