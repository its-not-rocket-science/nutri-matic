# Stock recipe library

A curated set of recipes visible to every Nutri-Matic user — browsable
under Collections, read-only, owned by a system account rather than any
real user, and "Copy to my recipes" away from becoming an editable recipe
in your own library. They exist to give a new user something real to
explore (search, scoring, robustness, dietary filtering) before they've
logged a single food themselves, and to demonstrate features — protein
complementarity, iron/vitamin-C pairing, absorbed vs. raw protein — with
deliberately chosen examples rather than whatever happens to already be in
someone's diary.

Built and maintained by `python -m app.stock_recipes`
(`backend/app/stock_recipes/`) — a standalone CLI, safe to run outside any
particular session, that discovers, sources, parses, matches, analyses,
and (only after a human approves a review file) imports recipes.

## How recipes are sourced

Two source kinds, selected per manifest entry
(`stock_recipes/seed_data/manifest.json`):

- **`manual`** — a hand-authored ingredient list in
  `stock_recipes/seed_data/manual_recipes.json`. No network access at all.
  This is how most of the initial library is populated: generic, standard
  versions of familiar dishes, written directly rather than copied from
  any specific page. A manifest entry can still carry a `source_url` even
  when its content is manual — that's purely an attribution/"view
  original" link shown to end users, never fetched or scraped.
- **`fetch`** — a live source adapter (`stock_recipes/sources/`) retrieves
  structured recipe data from a real page. Today's shipped adapter,
  `schema_org` (`sources/schema_org.py`), works against any site
  publishing standard [schema.org `Recipe`](https://schema.org/Recipe)
  JSON-LD.

### Supported sources

| Source | Status | Why |
|---|---|---|
| `pinchofnom.com` | Supported (`schema_org` adapter, verified) | `robots.txt` is fully open (`Disallow:` blank, no bot-specific blocks), its Terms page carries only a standard "don't republish our content commercially" copyright clause — no anti-scraping/anti-AI-training clause — and its recipe pages carry valid `Recipe` JSON-LD. UK-focused, budget/batch-cooking-oriented content besides. |
| Any other site with standard `Recipe` JSON-LD | Supported in principle | The adapter is generic — point a manifest entry's `source_url` at it and set `source_name: "schema_org"`. `fetch` will check that specific site's `robots.txt` itself before ever requesting a page; it doesn't trust the manifest's word for it. |

### Sources excluded because scraping isn't permitted

**BBC Food and BBC Good Food** — the two sources the original feature
request suggested — were checked live and are **excluded**. BBC's
site-wide Terms of Use, quoted directly from their `robots.txt` banner:

> No scraping, crawling, or systematic extraction of content. No use of
> BBC content for training or fine-tuning AI models, including large
> language models (LLMs). No retrieval-augmented generation (RAG),
> AI-powered search, agentic AI or grounding using BBC content. No text
> and data mining (TDM) under Article 4 of the EU Directive on Copyright
> in the Digital Single Market.

BBC Good Food's `robots.txt` additionally sets `Content-signal:
ai-train=no`. There is no compliant way to build a `schema_org` adapter
against either site, so none exists. A manual recipe's `source_url` may
still **link to** a BBC page purely for attribution/"read the original
method here" — that's outbound linking, not scraping, and is exactly what
this app already does for `Recipe.source_url` everywhere else.

### What's actually stored vs. discarded

Only what ingredient-level nutrition analysis needs:

- recipe title, canonical source URL, source name, licence (if declared)
- ingredient lines, parsed quantities/units, serving count
- retrieval timestamp, parser version, a content fingerprint (for change
  detection)

**Never** stored, even though a source's raw JSON-LD payload usually
contains it right alongside the ingredients: `recipeInstructions` (method
text), images, ratings/reviews, or any other descriptive/editorial prose.
The app sends users to the original source (`source_url`, rendered as a
"Source" link on the recipe page) to actually cook from.

## Ingredient parsing and unit conversion

`stock_recipes/ingredient_parser.py` turns a raw line ("2 cloves garlic,
crushed", "400g/14oz can chickpeas, drained and rinsed") into structured
fields — quantity (a min/max pair, so a stated range like "2-3 tbsp" isn't
collapsed to a single guessed number), unit, ingredient name, prep note,
optional flag, and a parsing confidence. It never invents a quantity for
an unspecified amount ("Salt, to taste" stays quantity-less). Handles UK
units, unicode/ASCII fractions, multipack notation ("2 x 400g tins"),
dual metric/imperial annotations, and common idioms ("juice of 1 lemon",
"a pinch of salt").

`stock_recipes/unit_conversion.py` converts a parsed quantity to grams —
exact for mass units, a density-table estimate for volume units (tsp/
tbsp/cup), and an ingredient-specific or generic unit-weight estimate for
counts (a clove, a tin, a slice). Every non-exact conversion is tagged
with a confidence tier (`exact`/`measured`/`estimated`) and, where
relevant, the specific assumption made — stored on
`RecipeIngredientProvenance.conversion_assumptions`, never concealed.

## How ingredient matching works

`stock_recipes/food_matching.py` resolves a parsed ingredient name to a
`Food` row, trying (in order, stopping at the first success):

1. **Alias** — `stock_recipes/ingredient_aliases.py`'s `ALIASES` table, a
   curated map from common recipe wording ("mince", "self-raising flour",
   "vegetable stock") to a cleaner search phrase. Confidence 0.95.
2. **Canonical** — a deterministic (non-fuzzy) `Food.name` prefix match.
   Confidence 0.85.
3. **Fuzzy** — the app's existing `search.search_foods_by_name` (the same
   service the diary/recipe-builder food search uses). Confidence 0.65
   (Foundation/SR Legacy) or 0.4 (branded — a branded product's name is
   marketing copy, a much weaker signal; see `dietary_tags.py`'s module
   docstring for the same reasoning applied to allergen matching).
4. **Manual review fallback** — `ingredient_aliases.py`'s
   `REVIEWED_FALLBACKS`, populated over time from review-file corrections
   for cases the first three tiers get wrong or miss entirely.

No LLM is involved anywhere in this — every match is either a curated
lookup or the app's existing deterministic/fuzzy search, so every match is
explainable and reproducible from its stored `match_method` alone.

An ingredient line that resolves to no `Food` at all (or resolves to a
`Food` but its quantity can't be honestly converted to grams — see
above) becomes an **unresolved ingredient**: recorded on
`Recipe.unresolved_ingredients` for transparency, but never a
`RecipeIngredient` row, so it can't silently distort the recipe's
nutrition totals.

**Coverage** is calculated two ways — proportion of ingredient *lines*
resolved, and proportion of ingredient *mass* resolved (more meaningful:
missing "salt, to taste" barely matters; missing the main protein source
does). A recipe below `--minimum-match-coverage` (line coverage) is held
at `needs_review` rather than auto-published.

### Troubleshooting food-match failures

1. Check the review file's `matches` entries for the ingredient — its
   `candidates` list shows what the fuzzy tier found, even when nothing
   was confident enough to auto-accept.
2. If the right food exists but under different wording, add an entry to
   `ALIASES` (recurring case) or `REVIEWED_FALLBACKS` (one-off) in
   `stock_recipes/ingredient_aliases.py` — no other code change needed.
3. If the food genuinely isn't in the database yet, it needs to be
   ingested first (`python -m app.ingest_fdc`, see the main README) or
   added via `python -m app.seed_manual_foods` for a pure-fat/oil/etc.
   that FDC ingestion always skips.
4. Rerun `match` (and `analyse`) for that candidate — no need to re-fetch.

## Public stock ownership

Stock recipes are owned by a real `User` row with `is_system=True` (see
`models.User.is_system`), created idempotently by `import-approved` the
first time it runs. Nobody can authenticate as this account: it's created
with an unknown random password (same pattern as the demo-account feature)
**and** `routers/auth.py`'s login endpoint explicitly refuses any
`is_system` user regardless of password — two independent layers, not
security-by-obscurity alone. Ownership then flows through the exact same
`user_id`-based checks every other recipe uses (`_get_owned_recipe`
requires `recipe.user_id == current_user.id`, which is simply never true
for anyone else) — there's no separate, hard-coded-ID special case
anywhere in the authorization logic.

## Collections

Ten "themed"/"educational" collections are manifest-assigned (a recipe's
`collections` list in `manifest.json`); six "dietary" collections (Vegan,
Vegetarian, Pescatarian, Gluten-Free, Dairy-Free, Nut-Free) are **computed**
at `analyse` time from the recipe's actual resolved ingredients, via the
app's existing `dietary_tags.evaluate_food` — the same engine
`dietary_filter.py` uses everywhere else. A recipe only qualifies when
*every* ingredient evaluates "ok" for that pattern; a single "unknown"
(typically a low-confidence branded-food match) or any unresolved
ingredient keeps it out. Unknown is never treated as safe.

No "pregnancy" collection exists. Nutrient totals alone can't establish
pregnancy safety (that needs e.g. listeria/mercury/vitamin-A-form
assessment this app has no data or model for), so it's omitted rather than
built on a claim the underlying analysis can't back up — see prompt
section 11 / `stock_recipes/collections_config.py`'s module docstring.

## How maintainers review recipes

Nothing publishes automatically. The pipeline stages
(`discover → fetch → parse → match → analyse`) only ever write to a local
JSON candidate cache (`--cache-dir`, default `./.stock_recipe_cache`);
`review-export` writes a review file — `review.json` (full fidelity,
authoritative for `import-approved`) and a sibling `review.csv` (the
actual editing surface: title, source, servings, coverage, unresolved-
ingredient count, overall robustness rating, warnings, flagged duplicates,
and a `proposed_publication_status` column).

To review: open the CSV, set `proposed_publication_status` to `approved`
or `rejected` for each row you've decided on (anything left as the default
`needs_review` publishes nothing), then run `import-approved`. Rejected
candidates are recorded as rejected in the cache but never written to the
database at all.

## What robustness ratings mean — and don't

`stock_recipes/robustness.py` runs a deterministic (seeded) Monte Carlo
simulation per recipe: each resolved ingredient's quantity is perturbed
within a bound derived from how precisely it was specified (tight for an
exact stated mass, wide for an approximate household measure or a
generic unit-weight guess), and the recipe is re-scored through the app's
**real** nutrition engine (`aggregation.py`, `scoring.py`,
`protein_absorption.py`, `bioavailability.py`) for each simulated draw.
The resulting 1-5 rating, per metric (protein, DIAAS/PDCAAS-absorbed
protein, DIAAS/PDCAAS protein quality, iron, calcium, fibre, sodium) and
overall, describes **how stable this recipe's calculated nutritional
conclusions are under plausible ingredient-quantity variation.**

It does **not** mean:

- the recipe is healthy, or appropriate for any particular user;
- the source recipe itself is reliable or well-tested;
- every ingredient can be freely substituted;
- any clinical outcome is guaranteed;
- every nutrient value involved is precisely known — poor ingredient-match
  coverage or missing digestibility data caps the rating rather than being
  ignored (see `robustness._rating_for`).

A metric this app has no validated model for (there is currently no
phytate/oxalate/tannin absorption-modifier data anywhere in the codebase —
see `bioavailability.py`'s module docstring) is reported as
`not_calculated` with a stated reason. Nothing is fabricated to fill the
gap. "Iron robustness" specifically reuses `bioavailability.py`'s existing
vitamin-C/meat-fish-poultry-aware absorption estimate (not raw iron mg) —
so its explanation can genuinely say something like "iron robustness is
low because most of the estimated available iron depends on the quantity
of red pepper, which supplies the meal's vitamin C," because that's
literally what got simulated.

The overall rating is **not a naive mean** of the per-metric ratings — it's
biased toward the weakest calculated metric, so one fragile,
single-ingredient-dependent nutrient can't be smoothed away by several
stable ones (see `robustness._overall`).

## Running the importer

```bash
cd backend
python -m app.stock_recipes discover
python -m app.stock_recipes fetch          # live network for source="fetch" entries
python -m app.stock_recipes parse
python -m app.stock_recipes match
python -m app.stock_recipes analyse        # runs the Monte Carlo simulation
python -m app.stock_recipes review-export  # writes review.json + review.csv
# ... edit review.csv's proposed_publication_status column ...
python -m app.stock_recipes import-approved
python -m app.stock_recipes report
```

Useful options (all stages except `report`/`import-approved` accept the
filtering ones): `--source`, `--collection`, `--limit`, `--dry-run`,
`--force-refresh`, `--cache-dir`, `--review-file`,
`--minimum-match-coverage`, `--simulation-count`, `--random-seed`,
`--verbose`. Run `python -m app.stock_recipes <command> --help` for the
full per-command list.

### Refreshing already-imported recipes

```bash
python -m app.stock_recipes refresh
```

Re-fetches every already-imported `fetch`-sourced recipe and compares its
content fingerprint against what was stored at last import. On a genuine
change, it flags the recipe `needs_review` and refreshes that candidate's
cache entry back to `discovered` for a fresh `parse`/`match`/`analyse`/
`review-export` pass — it **never** touches the recipe's existing
`RecipeIngredient` rows itself. Only a subsequent, explicitly
human-approved `import-approved` run ever replaces them. This is the
"avoid replacing manual corrections silently" guarantee: even an
unattended, scheduled `refresh` run can't quietly rewrite a recipe a
maintainer previously hand-corrected.

`refresh` has nothing to do for `manual`-sourced recipes — edit
`manual_recipes.json` and run `discover`/`fetch`/`parse`/`match`/
`analyse`/`review-export`/`import-approved` for that slug like any other
update.

### Rerunning analysis after a nutritional-model change

Robustness results carry the `robustness.ROBUSTNESS_MODEL_VERSION` they
were computed with, and DIAAS/PDCAAS scores depend on
`methodology.SCORING_METHODOLOGY_VERSION`/the digestibility reference
table. After changing either:

```bash
python -m app.stock_recipes analyse --collection <affected-collection>
python -m app.stock_recipes review-export
# review, then:
python -m app.stock_recipes import-approved
```

`analyse` recomputes both nutrition and robustness from the recipe's
current resolved ingredients — no re-fetch or re-match needed unless the
source or matching itself changed.

## Adding a source adapter

Implement `stock_recipes/sources/base.py`'s `SourceAdapter` protocol
(`fetch(entry, cache_dir, force_refresh) -> RawRecipe`, raising
`SourceUnavailable` for anything that isn't a success) and register it in
`sources/__init__.py`'s `build_adapters()`. Most new schema.org-JSON-LD
sites need **zero new code** — see `sources/schema_org.py`, which is
already generic; just add manifest entries with `source: "fetch"`,
`source_name: "schema_org"`, and that site's URL. Before doing so, check
that site's `robots.txt` and Terms of Use yourself first (the adapter
enforces `robots.txt` live at fetch time regardless, but you shouldn't
add a source you already know prohibits this in its terms — see the BBC
exclusion above for what that looks like).

## Adding manually curated recipes

Add a target entry to `stock_recipes/seed_data/manifest.json`
(`slug`, `name`, `collections`, `source: "manual"`, optionally an
attribution `source_url`, `priority`, `notes`), then add the matching
ingredient list to `stock_recipes/seed_data/manual_recipes.json`, keyed by
the same slug:

```json
"my_new_recipe_slug": {
  "servings": 4,
  "ingredients": [
    "500 g chicken breast, diced",
    "1 onion, chopped",
    "2 cloves garlic, crushed"
  ]
}
```

Write ingredient lines yourself — generic/standard quantities for the
dish, not copied from any specific page — then run
`discover → fetch → parse → match → analyse → review-export`, review, and
`import-approved`.

## Migrations and deployment

New tables (`recipe_ingredient_provenance`, `robustness_results`) are
created automatically by `Base.metadata.create_all()` on next backend
startup, same as any other new table. New columns on existing tables
(`users.is_system`, several `recipes.*` and `collection_recipes.*`
columns) need the manual `ALTER TABLE` block in
[DEPLOYMENT.md](../DEPLOYMENT.md)'s "Manual migrations needed on an
existing database" section, run once against any database that predates
this feature.
