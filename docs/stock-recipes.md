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
   "vegetable stock") to an `AliasTarget` (search phrase plus a
   `relationship` — `exact`/`regional_equivalent`/`close_analogue`/
   `category_proxy` — and its confidence, rationale, and provenance
   notes). Confidence 0.95 down to 0.65 depending on `relationship`; see
   the module docstring for what each relationship claims.
2. **Canonical** — a deterministic (non-fuzzy) `Food.name` prefix match.
   Confidence 0.85.
3. **Fuzzy** — the app's existing `search.search_foods_by_name` (the same
   service the diary/recipe-builder food search uses). Confidence 0.65
   (Foundation/SR Legacy) or 0.4 (branded — a branded product's name is
   marketing copy, a much weaker signal; see `dietary_tags.py`'s module
   docstring for the same reasoning applied to allergen matching).
4. **Manual review fallback** — `ingredient_aliases.py`'s
   `REVIEWED_FALLBACKS`, the same `AliasTarget` shape (relationship
   `reviewed_substitution`), populated over time from review-file
   corrections for cases the first three tiers get wrong or miss entirely.

No LLM is involved anywhere in this — every match is either a curated
lookup or the app's existing deterministic/fuzzy search, so every match is
explainable and reproducible from its stored `match_method` alone.

For an alias/manual-review match, `RecipeIngredientProvenance.
match_relationship` additionally records which `AliasRelationship` was
behind it (prompt section 8) — `GET /recipes/{id}` exposes
`match_method`/`match_confidence`/`match_relationship` per ingredient
(null for an ordinary, non-imported ingredient), and the recipe detail
page shows it as a small badge next to the ingredient. This is
informational only: nothing in `aggregation.py` reads it, so it can never
change a nutrition number, only how that number's provenance is presented.

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
   Once you know the specific Food row, pass `food_id=`/`expected_food_name=`
   to `reviewed(...)` so the mapping targets that stable id rather than
   relying solely on the fallback description search re-matching it correctly
   forever; `python -m app.stock_recipes match` runs `validate_reviewed_
   mappings` on every id-pinned entry and warns if a referenced food
   disappears or gets renamed out from under it.
3. If the food genuinely isn't in the database yet, it needs to be
   ingested first (`python -m app.ingest_fdc`, see the main README) or
   added via `python -m app.seed_manual_foods` for a pure-fat/oil/etc.
   that FDC ingestion always skips. If it's a category with no single FDC
   entry at all but a well-known composition (muesli is the shipped
   example), `seed_manual_foods.py`'s `COMPOSITE_FOODS` builds one by
   weighting real component foods already in the database through this
   app's own `aggregate_nutrients`/`aggregate_amino_acids` — a real,
   protein-weighted blend, not fabricated figures — rather than settling
   for a proxy to some other, adjacent food.
4. Rerun `match` (and `analyse`) for that candidate — no need to re-fetch.

### Maintainer guide: adding to the alias registry

All of these are one dict entry in `stock_recipes/ingredient_aliases.py`
— no other code change needed. Which helper you reach for depends on what
kind of claim you're making about the substitution (see "Why an alias
hierarchy" below for the reasoning; this is the practical how-to):

- **Adding an exact alias** — the recipe's wording is just a different
  way of saying the *same* food (a plural, a USDA-style reordering, a
  spelling variant). Use `exact("search phrase")`; the default rationale
  ("Same ingredient — search phrase normalised to the app's USDA-style
  naming.") is usually enough, but write a specific one if there's a
  real story (e.g. correcting a wrong canonical match).
- **Adding a regional equivalent** — a genuine UK/US naming difference
  for what's otherwise identical as food (`courgette`/`zucchini`,
  `mince`/`ground`). Use `regional("search phrase", "rationale explaining
  the naming difference")`.
- **Approving a nutritional proxy** — the database has no entry for the
  specific thing the recipe means, so you're picking either the closest
  *specific* substitute (`analogue(...)`, e.g. a variety/brand standing
  in for one the catalog lacks) or a broad stand-in for a whole missing
  *category* (`proxy(...)`, e.g. a spice blend or bread product with no
  dedicated entry at all). Both take a required `rationale` explaining
  why this is the closest available option, and an optional lower
  `confidence` override if the default (0.8 / 0.65) overstates how
  confident you actually are.
- **Recording a one-off reviewed substitution** — you've personally
  looked at a specific Food row and decided it's the right target for an
  ingredient nothing else resolves correctly. Use `reviewed("fallback
  search phrase", "rationale", fdc_id=..., expected_food_name=...)` (or
  `food_id=` if the target has no `fdc_id` — see "Why reviewed
  substitutions target a food_id" below for which to prefer) in
  `REVIEWED_FALLBACKS`, or in `ALIASES` if it's expected to recur.
- **Validating the registry** — run `python -m app.stock_recipes
  validate-aliases` after any of the above (and periodically/in CI): it
  checks every entry is well-formed (non-empty rationale/search phrase,
  in-range confidence, no duplicate keys) and, against a live database,
  that every pinned `fdc_id`/`food_id` still resolves, hasn't silently
  drifted to a renamed food, and has the nutrition coverage a
  protein-quality score needs. Exits 1 if anything needs attention.

## Principles

Four things worth stating explicitly, because they're easy to lose sight
of once the mechanics (below) get detailed:

- **Linguistic equivalence is not nutritional equivalence.** "Courgette"
  and "zucchini" naming the same vegetable is a fact about English, not
  about food composition — it happens to also be nutritionally exact here,
  but that's a property of the specific pair, not of "same/similar word"
  in general. "Garam masala" and "curry powder" are nowhere near
  linguistically related and aren't nutritionally identical either — the
  match exists purely because it's the closest available approximation,
  not because the words mean the same thing. Treating wording similarity
  as a proxy for nutritional similarity anywhere in this system would be a
  mistake; `AliasRelationship` exists specifically so the two questions
  ("is this the same words" vs. "is this the same food") are never
  conflated into one boolean.
- **Comments alone are insufficient provenance.** A code comment explains
  a decision to whoever reads the source — it says nothing to the end
  user seeing the recipe's nutrition numbers, and nothing to any code
  that might want to reason about match quality (a health check, a
  confidence threshold, a UI badge). Provenance that matters has to be
  data a program can read and a user can see, not prose only a future
  maintainer might stumble across.
- **Approximate substitutions must be visible and auditable.** A category
  proxy or reviewed substitution is a legitimate, often-necessary choice —
  the database will never have every dish's exact ingredient — but it's a
  choice a user is entitled to see, and a maintainer is entitled to
  re-check later. Hence: relationship + confidence + rationale on every
  entry, exposed through the API and the recipe detail page, `validate-
  aliases`/`validate_reviewed_mappings` to catch drift, and permanent
  regression tests so a wrong substitution can't quietly come back.
- **A successful match does not necessarily mean an exact match.**
  `food_matching.match_ingredient` returning a `Food` (as opposed to
  `None`) only means *something* resolved — it says nothing on its own
  about whether that something is the literal ingredient, a regional
  rename, or a coarse category stand-in. `MatchResult.relationship`/
  `confidence` are what actually answer that question; treating "matched"
  as "matched exactly" anywhere (a UI, a report, a future feature) would
  misrepresent what the matcher is actually claiming.

## Design rationale

The subsections above describe *how* matching, provenance, and robustness
work. This one is about *why* they're shaped the way they are — the
tradeoffs and prior failure modes each decision was actually responding to,
for whoever next has to decide whether to change one of them.

### Why an alias hierarchy instead of one flat mapping

Every alias/fallback entry used to be a bare `dict[str, str]`: normalised
ingredient phrase in, search phrase out. That worked as long as nobody
needed to ask *how much* to trust a given entry — but not every entry
deserves the same trust. "onion" -> "onions raw" is definitionally the same
food; "garam masala" -> curry powder is a coarse stand-in for a spice blend
this database simply doesn't have. Collapsing both into "an alias" made it
impossible to tell them apart from the data alone — a reviewer (or a future
maintainer) had to already know the history of each entry to know how far
to trust it.

`AliasRelationship` (`ingredient_aliases.py`) makes that distinction a
field instead of tribal knowledge: `exact` (same food, reworded),
`regional_equivalent` (a real UK/US naming difference for the same
product), `close_analogue` (a different variety/brand standing in because
the database has no entry for the specific thing), `category_proxy` (a
broad stand-in for a whole missing category — the coarsest, least certain
kind), and `reviewed_substitution` (a one-off a maintainer manually signed
off on). The five priority *tiers* food_matching.py already had (alias,
canonical, fuzzy, reviewed fallback) answer "in what order do we try to
match"; relationship answers "once matched via alias/fallback, how much
should this specific match be trusted" — an orthogonal question the tier
alone can't answer, since a single tier (ALIASES) contains entries from
four different relationship categories.

### Why reviewed substitutions target a food_id, not just a description

A `REVIEWED_FALLBACKS`/reviewed-`ALIASES` entry exists because a maintainer
already looked at one specific Food row and decided it was the right
target. Leaving that pinned only via a free-text search phrase means the
entry is re-derived from scratch on every match — and a description that
resolved correctly against today's catalog can start resolving to a
*different* row after a re-ingestion changes what's nearby (a new branded
product added, an existing entry's name tweaked). The entry would then
silently point somewhere else, with nothing in the data saying so.

`fdc_id`/`food_id` (+ `expected_food_name`, the name seen at review time)
let the entry target the exact row a human chose, permanently —
`search_phrase` becomes a fallback for the one case neither id can survive
(the referenced food is deleted or re-ingested under a new local id), not
the primary mechanism. `fdc_id` — USDA FoodData Central's own identifier —
is tried first and preferred wherever the target is a real FDC-derived
food, since it's stable across *any* database that ingests the same FDC
release; `food_id` (a local, auto-increment primary key) only matters for
something that isn't from FDC at all, like the generic-muesli composite.
`validate_reviewed_mappings` (run at the start of `match`, and by the
standalone `validate-aliases` command) is what catches a fallback actually
firing, a target renamed out from under its entry, or a preferred target
whose nutrition coverage (amino acids/digestibility) can't fully back a
protein-quality score — surfacing drift immediately rather than as an
unexplained match-quality regression discovered much later. The same
per-match signal (did *this specific ingredient* have to fall back, and
why) is also recorded on `RecipeIngredientProvenance` and surfaced by
`health-check` per recipe, not just at the registry level.

### Why confidence varies by relationship instead of one flat number

Every alias-tier match used to report a single flat confidence (0.95, or
0.9 for a reviewed fallback) regardless of what kind of match it actually
was — an "onions" -> "Onions, raw" match and a "garam masala" -> curry
powder proxy looked equally certain in the data, even though one is a
simple rewording and the other is a maintainer's best available
approximation. `DEFAULT_CONFIDENCE` ties confidence to `AliasRelationship`
instead (0.95 down to 0.65), so the number a user or developer sees
actually reflects how much interpretive judgment went into that specific
substitution — without touching a single nutrition calculation:
`aggregation.py` never reads `match_confidence`/`match_relationship` at
all, by design. Confidence is a *provenance* signal, not an input to a
sum — conflating the two would risk a future change quietly discounting a
recipe's nutrient totals based on how *sure* the matcher was, which isn't
what DIAAS/PDCAAS/energy math is supposed to mean.

### Why provenance is a separate table, exposed all the way to the frontend

`RecipeIngredientProvenance` is a 1:1 supplement to `RecipeIngredient`
rather than columns bolted onto it, so every existing user-recipe code
path is completely untouched by anything stock-recipe-specific — a plain
user-built ingredient has no row here at all, not an empty/null one.
Storing `match_method`/`match_confidence`/`match_relationship` was of
little use, though, as long as nothing ever read them back out: they sat
in the database purely for a maintainer willing to run a query. Exposing
them via `RecipeIngredientOut.provenance` and the recipe detail page's
per-ingredient badge (prompt sections 6/8) turns "we recorded how
confident this match was" into something an actual end user can see and
judge for themselves, without requiring them to trust an opaque bulk
"stock recipe" label — the same reasoning that motivated distinguishing
structured imports from manually-curated and adapted-composite recipes at
the recipe level (prompt section 6): provenance that only exists in the
database isn't really provenance a user has, it's an audit trail for
developers.

### Why the regression tests are negative, not just positive

Most test coverage asks "does the right thing happen." The permanent
fixtures in `test_stock_recipes_matching_regressions.py` deliberately ask
the opposite: "does the *wrong* thing stay impossible." That distinction
matters here specifically because every one of those fixtures documents a
match that was *silently, confidently wrong* before it was fixed — white
wine scored as if it were wheat, an egg as if it were eggnog — not a
crash, not an obvious data gap, but a wrong number that looked plausible.
A future refactor of `_word_and_search`'s ranking, the alias table, or the
canonical/fuzzy tiers could easily reintroduce one of these by accident
without any positive test noticing (the recipe would still "match
something," just the wrong thing again). Asserting the negative directly
— and keeping the fixtures even if the matching implementation
underneath them changes entirely — is what actually guards against
regression here, since "still returns *a* food" is not the same claim as
"still returns the *right* food."

### Why robustness analyses are immutable history, not an upserted row

`RobustnessResult` used to hold exactly one row per recipe, overwritten on
every re-analysis — correct for "what should the API return" (only the
latest result ever matters for that), but it meant every earlier analysis
was destroyed the moment a newer one ran, with no way to answer "did this
rating change because the model changed, or because the recipe's
ingredients did?" after the fact. That question comes up specifically
*because* this app already tracks `model_version`/`simulation_count`/
`random_seed` per result — those fields are only actually useful for
auditing/debugging/scientific comparison if more than one result survives
to compare. Making every analysis run insert a new row and flip
`is_latest` rather than mutate in place costs one boolean column and index;
in exchange, nothing about the recipe's analysis history is ever lost, while
`/recipes/{id}/robustness` and every other current-state view still only
ever see the one `is_latest=True` row — old analyses are there for whoever
goes looking, not something every caller has to filter out.

### Future-proofing review (prompt section 10)

A pass over the architecture above, looking specifically for changes that
would make future additions easier without touching any current matching
outcome:

* **Linguistic normalisation now lives in its own module**
  (`linguistic_normalisation.py`) instead of being defined inside
  `food_matching.py`. `normalise_ingredient_name` (lowercase, strip
  container words, collapse whitespace) carries no opinion about which
  food anything means — it's the same input every one of the matching
  tiers agrees on before any substitution judgement happens. Splitting it
  out makes that boundary a module boundary instead of something you have
  to read the whole file to notice. `food_matching.py` re-exports the
  function unchanged, so every existing import site and behaviour is
  identical — this was a pure move, verified by a test that the
  re-exported name and the module's own are the same function object, not
  a copy that could drift.
* **Reviewed substitutions were already made first-class objects, not
  dictionary entries** — prompt section 1's `AliasTarget` (`relationship`,
  `confidence`, `rationale`, `provenance`, optional `food_id`/
  `expected_food_name`) replaced the bare `dict[str, str]` alias tables.
  What was missing until now was *enforcement*: nothing stopped a new
  entry from being added with an empty rationale or an out-of-range
  confidence, relying on a reviewer noticing by eye. A schema-invariant
  test suite (`test_ingredient_aliases_schema.py`) now asserts, for every
  `ALIASES`/`REVIEWED_FALLBACKS` entry, that it really is an `AliasTarget`
  with a non-empty rationale, a valid `AliasRelationship`, a confidence in
  `(0, 1]`, a non-empty search phrase, and — for any entry pinning a
  `food_id` — a recorded `expected_food_name` (without which
  `validate_reviewed_mappings` could never distinguish "renamed since
  review" from "never had a name recorded"). A future entry that skips any
  of this now fails a test immediately, rather than being a silent gap.

Deliberately **not** done in this pass, and why:

* **Moving `ALIASES`/`REVIEWED_FALLBACKS` out of Python into a data file**
  (YAML/JSON) would let a non-engineer contribute entries without touching
  code. Not done here because `AliasTarget` currently benefits directly
  from being real Python — the `exact()`/`regional()`/`analogue()`/
  `proxy()`/`reviewed()` constructors give each relationship a sensible
  confidence default while still allowing an override, which a plain data
  file would need to reimplement as its own validation layer (and lose
  the "a typo in a relationship name is a Python `NameError`/`ImportError`
  at import time, not a silently-ignored bad row" property). Worth
  revisiting only if a non-engineer contributor workflow actually
  materialises — premature otherwise.
* **A general "linguistic normalisation" pipeline (stemming, broader
  synonym handling)** beyond what `search_foods_by_name` already does for
  the fuzzy tier was considered and rejected for now: every alias/
  canonical match's whole point is that it's *not* fuzzy — broadening
  `normalise_ingredient_name` itself risks it starting to silently paper
  over real distinctions the alias table exists to get right on purpose
  (see the section 3 regression fixtures). Any future normalisation work
  belongs in `search.py`'s fuzzy tier, which already owns that tradeoff,
  not here.

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

### Health-checking already-imported recipes

```bash
python -m app.stock_recipes health-check
```

Re-fetches every already-imported `fetch`-sourced recipe's source page (the
same adapter, robots.txt/rate-limit/caching rules `fetch`/`refresh` use),
and separately re-checks every imported recipe's alias/proxy provenance and
robustness freshness (fetch- or manual-sourced — matching applies to
both). Writes a report (`health_report.json` + a sibling `.csv`) of what it
finds, each row carrying a `severity` (`info`/`warning`/`critical`) and a
`recommended_action`:

- **dead_url** (critical) — the source page is now unreachable (404,
  robots disallow, no `Recipe` JSON-LD, etc.)
- **redirect** (warning) — the source URL now redirects somewhere else
- **canonical_url_changed** (warning) — the manifest's `source_url` has
  been edited since this recipe was last imported
- **content_changed** (warning) — the source's content fingerprint no
  longer matches what was last imported
- **missing_licence** (warning) — no source licence is recorded at all
- **licence_changed** (warning) — the source's licence text itself
  changed since last import
- **ingredients_changed** (warning) — the source's ingredient lines
  differ from what's stored in this recipe's provenance
- **nutrition_changed** (critical) — re-resolving the fresh ingredient
  lines through the normal match/aggregate pipeline produces a materially
  different (>15%) per-serving energy or protein figure
- **rematch_recommended** (warning) — a summary flag when the above
  suggest a maintainer should rerun `match`/`analyse` and re-review
  before republishing
- **preferred_target_missing** (warning) — an ingredient's alias/reviewed
  mapping had a preferred `fdc_id`/`food_id` that no longer resolved (the
  per-recipe instance of what `validate-aliases` checks at the registry
  level)
- **used_fallback_resolution** (info) — an ingredient resolved via the
  fallback description search rather than its preferred target
- **low_confidence_proxy** (info) — an ingredient resolved through a
  below-75%-confidence alias/reviewed match — the same "moderate
  confidence" cutoff the frontend badge uses, so what a maintainer sees
  here matches what an end user would see
- **stale_robustness** (info) — the recipe's latest robustness analysis
  predates the current `ROBUSTNESS_MODEL_VERSION`

Unlike `refresh`, `health-check` is **read-only**: it never writes to the
database, the candidate cache, or any `Recipe` row, even when it finds a
dead link or drifted content — it only produces the report above for a
maintainer to read and act on by hand, the same way `review-export`'s
output gets reviewed before `import-approved`. Run it on whatever schedule
suits (e.g. a periodic CI job); nothing about running it, however often,
can change a public recipe.

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

Every `import-approved`/`refresh` run that (re-)analyses a recipe inserts a
new, immutable `RobustnessResult` row rather than overwriting the last one —
the recipe's full analysis history survives (which model version, when,
under what simulation parameters), which is what lets you actually answer
"did this recipe's rating change because the model changed, or because its
ingredients did?" after a rerun like the one above. Exactly one row per
recipe has `is_latest=True`; the `/recipes/{id}/robustness` API and every
other current-state view only ever look at that one, so old rows are never
something a caller needs to filter out — they're there for direct-DB
auditing/debugging/scientific comparison, not routine display.

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
