# Canonical foods layer: investigation and plan

Status: **plan only**. Nothing in this document has been implemented. No
application code, schema, migration or data was changed to produce it.

Date: 2026-11-27.

## 0. How these numbers were produced (read this first)

- **No production database was queried.** Production is only reachable over
  SSH, which was out of scope. Every number below comes from the local
  Docker Postgres (`nutri-matic-postgres-1`, host port 5433), which holds a
  full FDC import: **1,435,277 `foods` rows**, matching production's
  ~1.43M. That copy is at alembic revision `2c049f319235`, one behind
  `main`'s head (`4cdb265fe305`, import manifests), which does not touch
  `foods`.
- Every query ran in a read-only transaction (`SET TRANSACTION READ ONLY` /
  `default_transaction_read_only=on`). Nothing was written.
- User-content counts (diary entries, recipes, prices) in the local copy are
  dev/demo data. They show *which tables* reference foods, not production
  volumes.
- A second local Postgres (native, port 5432) holds only the 7,857 generic
  rows and **no branded rows**. Search over it looks much better than over
  the full catalogue (generics win every query). The first search run
  accidentally used it. It is mentioned here because it shows the
  ranking problem below comes from the brands, not from missing generics.
- Appendix A has the census SQL so the numbers can be re-checked on
  production with a read-only session.

## 1. Findings

### 1.1 Data-type census

| `data_type` | Rows | With `gtin_upc` | Notes |
|---|---:|---:|---|
| `branded_food` | 1,427,396 | 347,384 (24.3%) | only **480,025 distinct names** (see 1.1.1) |
| `sr_legacy_food` | 7,460 | 0 | present |
| `foundation_food` | 420 | 0 | present |
| `NULL` | 1 | 0 | id 1, manual "Whey protein isolate" (no `fdc_id`) |
| survey / FNDDS | **0** | – | not imported |

**Foundation and SR Legacy are already present.** No import is needed to get
generic anchors for most staples. FNDDS (survey foods) is absent. The local
`data/` directory holds FDC zips for Branded (2026-04-30), Foundation
(2026-04-30) and SR Legacy (2018-04), but no FNDDS archive. Importing FNDDS
would mean adding its `survey_fndds_food` handling to `ingest_fdc.py`. It
is not needed for anything proposed here.

**Licence, from the repo's own records:**

- `docs/phytate-review/PRIVATE_ARTIFACTS.md` describes USDA FDC catalogue
  data as "public domain, independently obtainable from
  `fdc.nal.usda.gov`".
- The repo says nothing more formal than that. CC0 is not mentioned
  anywhere, and `backend/app/source_licence_policy.py` has no FDC entry (it
  only governs PhyFoodComp).
- So the repo supports "public domain" but has no formal FDC licence
  record. This plan does not depend on adding one, and it does not touch
  `source_licence_policy.py`. See open question Q8.

#### 1.1.1 Branded rows are mostly duplicate versions of the same product

FDC Branded publishes a new `fdc_id` each time a product's label data is
updated, and all versions were ingested.

| Versions of the same product name | Distinct names |
|---:|---:|
| 1 | 174,457 |
| 2 | 93,234 |
| 3 | 65,961 |
| 4 | 65,823 |
| 5 | 32,531 |
| 6–12 | ~41,000 |

`ingest_fdc.py` keeps a GTIN only on the **first** row that claims it.
Later versions with the same GTIN are stored with `gtin_upc = NULL`
(`duplicate_barcode_skipped`). In practice **a barcode resolves to the
oldest version of the label**. Example: "Ahold Usa, Inc. BAKED BEANS"
has six rows (fdc 393551 … 1658677). Only the two oldest carry a GTIN.

This duplication is also why search top-5 lists are often one product
repeated five times (1.2).

### 1.2 Search today

**Code path.** `GET /api/foods/search-by-name` →
`search.search_foods_by_name(db, q, limit)`. The frontend calls it with
`limit=15`. Then `dietary_filter.filter_excluded_foods` runs.

1. `expand_query_terms`: the lowercased query, plus a crude singular or
   plural form, plus `FOOD_SYNONYMS`. That is a hand list of 23 keys,
   e.g. aubergine↔eggplant, courgette↔zucchini, coriander↔cilantro,
   beef mince↔ground beef.
2. Candidate pool: `name ILIKE '%term%'` for any term, **ordered
   non-branded first**, then by name, `LIMIT limit*5` (75).
3. Final rank, `_rank_by_relevance`, in Python: exact match, then prefix
   match, then `difflib.SequenceMatcher` similarity **to the raw query**.
   **`data_type` is not in the sort key.**
4. If there are fewer than `limit` results on Postgres, a trigram fallback
   adds matches: `name % :q ORDER BY name <-> :q`, threshold 0.2.

**Results.** These came from running the real `search_foods_by_name` at
`limit=15` against the full local catalogue, in read-only transactions.
Key: F = foundation, SR = SR Legacy, B = branded.

✓ means the top result is a sensible generic answer. ~ means it is the
right food, but a brand or US product where a generic exists. ✗ means the
wrong food.

| # | Query | Top 5 (type: name, truncated) | Top OK? |
|---|---|---|:-:|
| 1 | chickpeas | F: Chickpeas, dry · SR: Chickpeas, mature seeds, raw · SR: …canned, drained solids · SR: …cooked, boiled, with salt · F: …canned, sodium added, drained and rinsed | ✓ |
| 2 | canned chickpeas | B: 13 FOODS CHICKPEAS · SR: Chicken, canned, no broth · B: CASERA CHICK PEAS · SR: Pate, chicken liver, canned · B: BIO-BUD SPROUTED CHICKPEAS | ✗ |
| 3 | dried chickpeas | B: 13 FOODS CHICKPEAS · SR: Seeds, chia seeds, dried · B: BIO-BUD SPROUTED CHICKPEAS · B: PEREG CHICKPEA · B: LIOR CHICKPEAS, 17.6 OZ | ✗ |
| 4 | lentils | F: Lentils, dry · SR: Lentils, raw · SR: Lentils, sprouted, raw · SR: Lentils, pink or red, raw · SR: Lentils, mature seeds, cooked, boiled, with salt | ✓ |
| 5 | porridge oats | B: Traditional Irish Foods ORGANIC PORRIDGE OATS ×3 · B: …OLD WESSEX… PORRIDGE OATS CEREAL ×2 | ~ |
| 6 | semi-skimmed milk | B: INSTANT SKIM MILK · B: Moo-Ville SKIM MILK ×3 · B: KLEINPETER SKIM MILK | ✗ (wrong fat level) |
| 7 | wholemeal bread | B: ODLUMS STONEGROUND WHOLEMEAL BREAD MIX · B: SONKO CRISP BREAD WHOLEMEAL · B: WHOLE WHEAT BREAD · B: 100% WHOLE WHEAT BREAD ×2 | ✗ |
| 8 | mince | SR: Ham, minced · B: BEEHIVE MINCE PIE · B: BROOKSHIRE'S… MINCE PIE · SR: Pie, mince · B: …MINCE PIE | ✗ |
| 9 | beef mince | B: AVA INC GROUND BEEF PATTIES · B: ALL NATURAL GROUND BEEF PATTIES · B: Ahold… GROUND BEEF PATTIES ×3 | ✗ |
| 10 | aubergine | B: Artforum Internat'L. Magazine EGGPLANT DIP ×5 | ✗ |
| 11 | eggplant | SR: Eggplant, raw · F: Eggplant, raw · SR: Eggplant, pickled · SR: …cooked, boiled, with salt · SR: …without salt | ✓ |
| 12 | courgette | B: Authentic Joy ZUCCHINI SPIRALS WITH BASIL PESTO ×4 · SR: Squash, summer, zucchini, …frozen | ✗ |
| 13 | zucchini | SR: Squash, zucchini, baby, raw · B: Ahold… SLICED ZUCCHINI ×4 | ✓ |
| 14 | coriander | SR: Coriander (cilantro) leaves, raw · SR: Spices, coriander seed · SR: Spices, coriander leaf, dried · B: …CILANTRO SALSA · B: …TILAPIA WITH CILANTRO LIME BUTTER | ✓ |
| 15 | cilantro | SR: Coriander (cilantro) leaves, raw · B: …CILANTRO SALSA · SR: Spices, coriander seed · B: …TILAPIA… ×2 | ✓ |
| 16 | rocket | B: Rocket Science Games, Inc. BBQ SAUCE ×4 · B: Rocket Science Games… INVIGORATE JUICE | ✗ |
| 17 | arugula | SR: Arugula, raw · F: Arugula, baby, raw · B: PETITE ARUGULA · B: BABY ARUGULA ×2 | ✓ |
| 18 | spring onion | B: BAJASON GREEN ONIONS · B: Baja Son Growers… GREEN ONIONS ×4 | ~ |
| 19 | scallion | B: Aldon… SCALLION CREAM CHEESE ×2 · B: …GREEN ONIONS ×3 | ✗ |
| 20 | swede | B: Wasabrod Ab Sweden SANDWICH ×3 · B: Wasabrod Ab Sweden CRISPBREAD ×2 | ✗ |
| 21 | crisps | SR: KFC, Crispy Chicken Strips · B: 34 DEGREES CHOCOLATE CRISPS · SR: Crackers, crispbread, rye · SR: WENDY'S, Crispy Chicken Sandwich · B: …CHOCOLATE SWEET CRISPS | ✗ |
| 22 | chips | SR: Snacks, taro chips · SR: banana chips · SR: brown rice chips · SR: bagel chips · SR: pita chips | ✗ (US sense, and not potato) |
| 23 | biscuit | SR: Biscuits, plain or buttermilk, dry mix · …refrigerated dough · …frozen, baked · …dry mix, prepared · …prepared from recipe | ✗ (US scone-like biscuit) |
| 24 | jam | SR: Jams and preserves · SR: …apricot · SR: …no sugar · B: BLUEBERRY JAM · B: …JAMBALAYA SAUCE | ✓ |
| 25 | double cream | B: Double Cream French Brie · B: DOUBLE CREAM BRIE… · B: Double Cream Cremont… cheese · B: Hy-Vee DOUBLE CREAM BRIE ×2 | ✗ |
| 26 | plain flour | B: Pams Pure Plain Flour 5kg · B: …1.5kg · F: Flour, 00 · SR: Potato flour · F: Flour, potato | ~ |
| 27 | caster sugar | B: SUGAR COOKIE, SUGAR · B: SUGAR COOKIES, SUGAR ×2 · B: SUGAR SUGAR COOKIES · B: Gotera… SUGAR CANE | ✗ |
| 28 | tinned tomatoes | B: STRAINED TOMATOES · SR: Tomatoes, crushed, canned · F: Tomatoes, crushed, canned · B: TIP TOP DICED TOMATOES · B: CHOPPED TOMATOES | ~ |
| 29 | baked beans | B: Ahold Usa, Inc. BAKED BEANS ×5 | ~ (US-style) |
| 30 | cheddar | F: Cheese, cheddar · B: 2-YEAR AGED CHEDDAR · B: 5 YEAR CHEDDAR CHEESE · SR: LEAN POCKETS, Ham N Cheddar · SR: Cheese, cheddar, sharp, sliced | ✓ |
| x | porridge | B: FOSKA OATMEAL INSTANT PORRIDGE · B: FOSKA CORNMEAL… · B: VIFON ARTIFICIAL CHICKEN PORRIDGE … | ✗ |
| x | houmous | B: HOUSE KOMBUCHA KOMBUCHA · B: Cedars Co. HOMMOUS DIP ×4 | ✗ |
| x | rapeseed oil | B: …ASTAXANTHIN (RED ALGAE), POMEGRANATE SEED… · F: Grapes, red, seedless, raw ×2 · F: Grapes, green… ×2 | ✗ |
| x | kidney beans | B: Ahold USA, Inc. DARK KIDNEY BEANS ×5 | ~ |

**Score over the 30 required queries: 9 ✓, 5 ~, 16 ✗.**

A generic row that would be a good answer exists for every ✗ and ~ above,
for example:

| Query | Existing generic row |
|---|---|
| canned chickpeas | F "Chickpeas …, canned, sodium added, drained and rinsed" |
| semi-skimmed milk | SR/F "Milk, lowfat, fluid, 1% milkfat…" / reduced fat 2% |
| mince, beef mince | F/SR "Beef, ground, 80% lean meat / 20% fat, raw" |
| swede | F "Rutabaga, peeled, raw" |
| houmous | F "Hummus, commercial" |
| porridge oats | F "Oats, whole grain, rolled, old fashioned" |
| double cream | F "Cream, heavy" |
| wholemeal bread | F "Bread, whole-wheat, commercially prepared" |
| crisps | SR "Snack, potato chips…" |
| chips (UK) | SR "Potatoes, french fried, …" |
| biscuit (UK) | SR "Cookies, …" |

**Why it goes wrong.** Each cause is visible in the code above:

1. **Final ranking ignores `data_type`.** "Non-branded first" only decides
   which 75 rows enter the pool. Once inside, a short ALL-CAPS brand name
   often has higher `SequenceMatcher` similarity than a long
   "Head, modifier, modifier" FDC generic name.
2. **Similarity is measured against the raw query, not the term that
   matched.** "aubergine" matches only via the synonym "eggplant". After
   that, every candidate scores similarly badly against the string
   "aubergine", so the order is effectively arbitrary.
3. **Whole-phrase substring matching meets inverted FDC naming.**
   "canned chickpeas" is not a substring of "Chickpeas (…), canned, …".
   "ground beef" is not a substring of "Beef, ground, …". Multi-word
   queries miss the generic row and fall through to brands or the trigram
   fallback.
4. **UK vocabulary is missing from `FOOD_SYNONYMS`**: rocket, swede,
   crisps, chips, biscuit, double/single cream, caster/icing sugar, plain
   or self-raising flour, semi-skimmed, wholemeal, mince alone, houmous,
   tinned, rapeseed, porridge oats.
   - `stock_recipes/ingredient_aliases.py` already contains UK→US
     knowledge, with an honest relationship vocabulary (124 entries, e.g.
     plain flour, beef mince). It is only used for recipe import, never
     for search.
   - "chips" and "biscuit" mean different things in en-GB and en-US, so a
     symmetric synonym list cannot handle them.
5. **Duplicate branded versions fill the top 5** (1.1.1).
6. **The trigram fallback misfires and is slow.** rapeseed → grapes,
   houmous → kombucha. Local timings for queries that reach it:
   chickpeas 2.2 s, porridge oats 3.8 s, caster sugar **8.3 s**,
   dried chickpeas 4.9 s. Single-word substring hits take 20–200 ms.
7. **Preparation state plays no part in ranking.** For "aubergine", the
   salted, boiled row can outrank raw.

### 1.3 Nutrient completeness

This is the share of rows with a `food_nutrients` row for each key. A
missing row means "not reported". It does not mean zero.

| Nutrient | Branded (1,427,396) | SR Legacy (7,460) | Foundation (420) |
|---|---:|---:|---:|
| energy | 98.4% | 100.0% | **31.4%** |
| protein | 99.9% | 100.0% | 100.0% |
| fibre (`fiber_total`) | 95.4% | 92.9% | 58.6% |
| iron | 94.1% | 99.2% | 98.8% |
| zinc | **3.2%** | 95.2% | 98.8% |
| calcium | 93.8% | 99.1% | 98.8% |
| magnesium | **3.6%** | 95.4% | 98.8% |
| vitamin B12 | **3.1%** | 91.5% | 20.2% |
| folate (DFE) | **0.2%** | 83.1% | **0.0%** |
| vitamin D | 7.9% | 66.8% | 14.8% |

Implications:

- **Branded rows are label data.** They have energy, macros, iron and
  calcium, but almost no zinc, magnesium, B12 or folate. A diary built
  from branded rows shows false gaps for those nutrients, because they are
  unreported rather than low. An SR Legacy anchor fixes this for the
  gap-analysis dashboard, not just for search.
- **Foundation is not a drop-in "best generic".**
  - Energy shows for only 31% of rows. Foundation mostly reports
    Atwater-specific energy (nutrient 957/958) rather than nutrient 208,
    and `ingest_fdc.py` maps only 208. This is a likely cause; I have not
    verified it.
  - Folate (DFE, nutrient 435) is absent for every Foundation row.
  - **The canonical default should therefore prefer SR Legacy where
    Foundation lacks energy or folate.** Alternatively, fix the energy
    mapping as a separate, independent change (Q9).
- **Derived "typical" values (section 3.2) can never fill
  zinc, magnesium, B12 or folate.** Branded members simply do not report
  them.

### 1.4 Barcode path

- **API**: `GET /api/foods/barcode/{gtin_upc}` →
  `Food.gtin_upc == gtin_upc`, an exact string comparison. It returns
  `404 {"detail": "No food found for that barcode"}` on a miss.
- **Frontend**: `BarcodeScanner.svelte` decodes with `@zxing/browser`, or
  accepts a typed code. It passes `result.getText()` unchanged to
  `diary/+page.svelte` `handleScan` → `api.getFoodByBarcode`.
  - On a hit, the food is preselected in the add-entry form.
  - On a miss, the scanner closes and the page's error banner shows
    **"No food found for that barcode"**. There is no fallback to name
    search, no "add this product" flow, and nothing is logged for
    follow-up.
  - No external service is called.
- **No normalisation.** GTINs are stored in whatever width FDC published:

| Stored GTIN length | Rows |
|---:|---:|
| 12 (UPC-A) | 289,924 |
| 14 (GTIN-14) | 24,258 |
| 13 (EAN-13) | 23,988 |
| 11 | 7,110 |
| 8 | 1,884 |
| other (5–18) | 220 |
| containing non-digits | 68 |

- 20,975 rows are stored as 14 digits with a leading `0`. A phone scanner
  reading the pack's EAN-13 returns 13 digits, so **these never match**.
  Of those, 904 also have a different row stored under the 13-digit form,
  so normalisation must resolve collisions deterministically.
- **UK coverage is tiny.**
  - 543 rows carry a UK (GS1 prefix `50`) EAN-13 as 13 digits.
  - About 115 more UK codes are stored zero-padded to 14 digits.
  - The total is under 0.05% of the catalogue. Most UK supermarket
    products will 404.
- **Version.** As 1.1.1 notes, a barcode hit returns the oldest label
  version of the product.

**Hand-test list: 15 UK barcodes.** All of these are taken from the local
catalogue copy. Production should be identical if it came from the same
import. I did no external lookups, and I have not checked real packs, so
a current pack may carry a different code.

| # | Scan or type | Expect today | What to look for |
|---|---|---|---|
| 1 | 5000232901286 | hit: BATCHELORS BIGGA MARROWFAT PROCESSED PEAS | Baseline hit. Few nutrients (5 rows). |
| 2 | 5000183501108 | hit: CADBURY MILK CHOCOLATE SPREAD | Few nutrients (4 rows). Gap analysis will show false gaps. |
| 3 | 5010909004929 | hit: CAMPBELLS PURE SHORTBREAD TEDDIES | Baseline hit. |
| 4 | 5027017160102 | hit: NISHA'S JELLY BABIES | Baseline hit. |
| 5 | 5060054134040 | hit: CAWSTON PRESS TRADITIONAL JUICE | Baseline hit. |
| 6 | 5054267004795 | hit: LUCOZADE ENERGY SPARKLING | 8 versions exist. Check that the returned label is the oldest. |
| 7 | 5034660520665 | **404** (stored as `05034660520665`, Cadbury Creme Egg) | Padding bug. Typing the 14-digit form manually should hit. |
| 8 | 5034660505181 | **404** (stored as `05034660505181`, Curly Wurly) | Same. |
| 9 | 5034660520191 | **404** (stored as `05034660520191`, Twirl) | Same. |
| 10 | 5034660521501 | **404** (stored as `05034660521501`, Trebor Extra Strong Mints) | Same. |
| 11 | 5000183036853 | **404** (stored as `05000183036853`, Cadbury Snack Shortcake) | Same. |
| 12 | 5010455063135 | **404** (stored as `05010455063135`, Halls Soothers Cherry) | Same. |
| 13–15 | Scan three everyday UK own-label staples from your cupboard: semi-skimmed milk, a wholemeal loaf, a tin of chopped tomatoes | 404 expected | Shows the real-world miss rate and the current dead-end UX. Note what you would have wanted to see. |

For rows 7–12, if the scanner app reads 14 digits, note that too. The
point is to see what width the zxing decoder hands over for EAN-13 on your
phone.

### 1.5 Phytate interaction and preparation state

**How preparation is represented today:**

- **Foods**: preparation exists only inside the FDC name text, e.g.
  "…, dry", "…, mature seeds, raw", "…, canned, drained solids",
  "…, cooked, boiled, with salt". No column holds it.
- **Diary**: there is no preparation field. An entry is
  `(food_id, quantity_g)`, so the preparation is whatever the chosen food
  row's name implies.
- **Phytate**:
  - `compound_observations.source_preparation_state` is free text in the
    source's own words. It is always populated in the local copy.
  - Observations link to a food only through `matched_food_id`. The match
    is reviewed and carries a `match_relationship` of exact /
    regional_equivalent / close_analogue / category_proxy / needs_review.
  - `phytate_selection.select_phytate_observations(db, food_id, surface,
    preparation_context=…)` selects by that **one concrete `food_id`**.
  - `preparation_context` is a query parameter on `GET
    /api/foods/{id}/phytate`, but **the frontend never sends it**. So
    `preparation_compatible` is always `None` in the UI today.
  - Even when it is sent, it is metadata only (a substring check) and
    never a filter.
- **Local match aggregates** (counts only, no source content):
  - 3,941 observations.
  - Accepted matches (not needs_review): 438 `regional_equivalent`, 334
    `category_proxy`, 77 `close_analogue` (3 of them to branded rows, the
    rest to SR Legacy/Foundation).
  - 1,558 needs_review rows point at branded candidates.

**Dry and canned are not interchangeable.**

| Row | Protein g/100 g |
|---|---:|
| Chickpeas, dry (F) | 21.3 |
| Chickpeas, raw (SR) | 20.5 |
| Chickpeas, cooked, boiled (SR) | 8.9 |
| Chickpeas, canned, drained (F) | 7.0 |
| Chickpeas, canned, drained solids (SR) | 7.1 |

Phytate per 100 g as eaten shifts in the same direction, through water
uptake and soaking or cooking losses.

The branded chickpea rows (2,216, excluding obvious hummus, snacks, pasta
and so on) are **bimodal**: 1,384 below 10 g protein (canned) and 426 at or
above 20 g (dry). Their median is 6.72 g, which is a canned figure. A
"typical chickpeas" median would be wrong for anyone logging dry
chickpeas.

**Where a canonical layer could go wrong:**

1. **Grouping across preparation states.** If canonical "chickpeas" groups
   dry, boiled and canned rows, and its default or representative member
   is used for logging, a user who cooked dried chickpeas gets canned
   numbers, or the reverse. The error is roughly 3× in protein, minerals
   and phytate.
2. **Phytate looked up through the canonical rather than the logged
   `food_id`.** If phytate were resolved "for chickpeas" via any member, a
   dry-basis observation reviewed against the dry row would be shown
   against a canned entry. The reviewed match was made for one specific
   food, and borrowing it silently defeats `match_relationship`.
3. **Re-pointing the representative member.** If the canonical's default
   member changes from SR "…canned, drained solids" to F "…canned, sodium
   added, drained and rinsed", phytate coverage for new entries changes.
   One row may have an accepted observation and the other may not.
4. **Synthetic "typical" food rows.** These would have no phytate match at
   all, and would change the FDC catalogue checksum (1.6).
5. **Medians over branded members of mixed preparation state** (above).
   Branded names often omit the state ("13 FOODS CHICKPEAS"), so state
   cannot always be inferred. Those rows must be excluded, not guessed.
6. **The substring preparation check.** `_preparation_compatible` does
   `context in source_preparation_state`. A canonical preparation
   vocabulary ("canned_drained") would not substring-match the source's
   prose. Any future wiring needs an explicit mapping, not reuse of the
   enum string.
7. **Licence surface.** The canonical layer must not become a new route to
   PhyFoodComp data:
   - No phytate values or source descriptions are copied into canonical
     tables or review files.
   - No canonical endpoint returns compound data.
   - The canonical review file is built only from FDC names and
     hand-written terms. In particular, it is never seeded from the
     untracked `docs/phytate-review/final_approved_mapping.csv`.
   - `/api/foods/{id}/phytate` stays the only phytate route, keyed by a
     concrete food and gated by `source_licence_policy` exactly as now.

### 1.6 Where foods are referenced (blast radius)

**Foreign keys to `foods.id`** (8):

| Table | Column | Null? | Local refs by type |
|---|---|---|---|
| `food_nutrients` | `food_id` | not null | 14,107,033 rows |
| `diary_entries` | `food_id` | nullable (XOR recipe) | 118 SR, 34 F, 1 manual |
| `recipe_ingredients` | `food_id` | not null | 1,000 SR, 257 F, **411 B** |
| `meal_plan_entries` | `food_id` | nullable | 24 SR |
| `meal_plan_template_entries` | `food_id` | nullable | 0 |
| `diary_meal_template_items` | `food_id` | nullable | 0 |
| `food_prices` | `food_id` | not null | 25 SR |
| `compound_observations` | `matched_food_id` | nullable | see 1.5 |

**Favourites:** there is no favourites table or feature. A search of
`backend/app` and `frontend/src` finds no "favourite" or "favorite". The
nearest things are the diary quick-add (recent and frequent foods, derived
from `diary_entries`) and the meal templates above.

**Stable-ID and non-FK references:**

- `catalogue_manifest.py` computes a checksum over
  `(id, fdc_id, name, data_type)` of **every** `foods` row, manual rows
  included. That checksum is the drift detector for the phytate stable-ID
  mapping. **Adding, renaming or retyping any `foods` row changes it.**
- The phytate review and resolver files (`resolve_phytate_stable_ids.py`,
  `validate_stable_id_mapping.py`, `import_reviewed_phytate_mappings.py`,
  `docs/phytate-review/*`) key on `fdc_id`.
- `recipe_ingredient_provenance` and `stock_recipes/food_matching.py`
  resolve recipe lines through `search_foods_by_name`. **Changing search
  ranking changes what future stock-recipe imports match.** Existing
  recipes keep their stored `food_id`.
- `diary_snapshots.summary_json` holds frozen computed payloads. It stays
  valid as long as food rows are not mutated.
- Exports: the only export-ish code is phytate-review scripts. There is no
  user diary export endpoint today.
- `data_type` is read in 19 backend modules: dietary filter and tags,
  recommendations, candidate metadata, data-quality audit, the phytate
  resolvers, and others.
- Tests: 67 of 127 backend test modules reference `food_id`.
  `test_search.py` has 28 tests, and `test_ingredient_aliases_schema.py`
  pins the alias vocabulary.

**Conclusion: any design that keeps `foods` rows and their ids untouched,
and keeps diary, recipe and plan rows pointing at concrete foods, has
almost no blast radius.** Designs that add rows to `foods` or replace
`food_id` with a canonical id touch all of the above.

## 2. Options considered

| | Option | What it fixes | Cost / risk | Verdict |
|---|---|---|---|---|
| A | **Search-only fixes.** Rank by data type in the final sort, token-AND matching, en-GB synonyms, collapse branded versions, prep-aware tie-break. | Most of 1.2: rocket, swede, aubergine, canned chickpeas, crisps… | Backend only, no schema. "chips" and "biscuit" need a locale rule. | **Do first** (PR 1). |
| B | **Canonical layer in separate tables** pointing at existing foods (`canonical_food`, `canonical_alias`, `canonical_member`). Diary still stores a concrete `food_id`. | One curated "chickpeas (canned, drained)" answer per concept, provenance, locale-aware aliases, a basis for dedup. | Additive migration. Needs a review workflow. | **Recommended** (PR 4+). |
| C | Insert synthetic "typical" foods into `foods` | Lets a median be logged directly | Changes the catalogue checksum and trips drift detection. Mixes derived and FDC rows. No phytate match. Risky to reverse once logged. | **Rejected.** |
| D | Replace `diary_entries.food_id` with `canonical_food_id` | Canonical analytics | Touches 8 FK tables. Breaks the phytate `food_id` keying and snapshots. | **Rejected.** |
| E | Import UK composition data (CoFID) or Open Food Facts for UK barcodes | Real UK products and composition | Out of scope here (no new sources, no downloads). Licences are not recorded in the repo and need their own review. OFF is a share-alike database licence, as I recall it, unverified. | **Later, separate decision** (Q7). |

## 3. Recommended design

### 3.1 Schema sketch (additive; nothing existing is altered)

```text
canonical_food
  id                 PK
  key                text unique        -- "chickpeas.canned_drained"
  display_name_en_gb text               -- "Chickpeas, tinned, drained"
  display_name_en_us text
  concept            text               -- "chickpeas" (groups variants)
  preparation_state  text not null      -- closed vocabulary, see below
  default_food_id    FK foods.id null   -- concrete row used when logging
  status             text               -- active | retired
  review_ref         text               -- row id in the reviewed file
  created_at, updated_at

canonical_alias
  id, canonical_food_id FK, alias text, locale text ('en-GB'|'en-US'|'*'),
  relationship text   -- exact | regional_equivalent | close_analogue | category_proxy
                      -- (same vocabulary as ingredient_aliases.py)
  unique(locale, alias, canonical_food_id)

canonical_member
  canonical_food_id FK, food_id FK foods.id,
  match_method text   -- reviewed | rule:<name>
  confidence   text   -- high | medium | low   (not a model score)
  role         text   -- anchor | member | excluded
  unique(canonical_food_id, food_id)

canonical_typical_value          -- section 3.2; only for canonicals with no anchor
  canonical_food_id FK, nutrient_key, median, p25, p75, n_members,
  computed_from_catalogue_checksum text, computed_at
```

**Preparation is first-class and closed:**

- Values: `unspecified`, `raw`, `dry`, `soaked`, `sprouted`,
  `cooked_boiled`, `canned_drained`, `canned_with_liquid`, `frozen`,
  `roasted`, `fried`, `dehydrated`.
- It is enforced by a CHECK constraint, the same way the
  `compound_observations` vocabularies are.
- **A canonical food has exactly one preparation state.** "Chickpeas" is
  a *concept* spanning several canonical foods, not one food.
- Invariant, tested and checked at load time: every `anchor` or `member`
  of a canonical food has a classified preparation state equal to the
  canonical's state. Branded rows whose state cannot be classified may be
  `excluded`, never `member`.

**Diary, recipes and plans keep storing a concrete `food_id`.**

- Selecting a canonical result in search logs its `default_food_id`, an
  existing SR or Foundation row, or a branded medoid (3.2).
- Every existing entry, recipe ingredient, template, snapshot and barcode
  stays valid by construction.
- The phytate endpoint keeps receiving that concrete id. Canonical tables
  are **never** consulted for phytate (1.5 #2).

**Keys use `fdc_id`, not `foods.id`, in the reviewed file.** The loader
resolves them to ids per environment. This matches the phytate stable-ID
pattern and survives a re-import.

### 3.2 "Typical" values when no generic row exists

- **Prefer an anchor.** If an SR or Foundation row exists for the
  concept and state, it is the default. No derivation happens. This
  covers every query in 1.2.
- **Derive only when all of these hold:**
  - there is no anchor;
  - there are at least 10 *distinct products* as members, after
    collapsing versions;
  - every member has the same classified preparation state;
  - the per-nutrient spread is tight: an IQR/median ceiling, e.g. 0.5 for
    energy and protein (Q4);
  - a nutrient is only derived if at least 50% of members report it.
- **Never derive:**
  - across preparation states;
  - when the protein or energy distribution is bimodal (the chickpea case
    in 1.5);
  - for nutrients branded labels rarely report: zinc, magnesium, B12,
    folate and vitamin D in practice (1.3). Those show as "not reported",
    never 0;
  - for anything phytate-related.
- **What gets logged.** The *medoid*: the real branded member closest to
  the median vector. Logging a real row keeps `food_id` concrete and the
  catalogue checksum unchanged. The medians themselves are display-only
  provenance.
- **What the user sees:** "Typical of 37 branded products (median, USDA
  Branded Foods). Logged as: <medoid name>." Plus per-nutrient "reported
  by 31 of 37" where it is not all of them. An anchor shows "USDA SR
  Legacy" or "USDA Foundation" with the row name. A UK→US substitution
  shows the alias relationship note, e.g. "UK double cream (~48% fat) is
  richer than US heavy cream (~36%)" for a `close_analogue`.

### 3.3 Search ranking

Barcode stays a separate endpoint. **An exact barcode is always exact.**
The canonical layer never intercepts a GTIN lookup.

Name search tiers, in order:

1. Canonical alias exact match in the request locale, then any locale
   (`'*'`). Each matching canonical shows as one result, with its
   preparation variants as sibling results ("Chickpeas, tinned, drained"
   · "Chickpeas, dried" · "Chickpeas, boiled").
2. Generic rows (Foundation, SR Legacy) matching **all query tokens**
   after alias, plural and locale normalisation, in any order. This fixes
   "canned chickpeas" → "Chickpeas …, canned".
   - Tie-break: preparation `unspecified`/`raw` first unless the query
     names a state. Then fewer extra modifiers. Then similarity to the
     *matched* term, not the raw query.
3. Branded rows, collapsed to one result per product (normalised name,
   newest `fdc_id`), same token rule.
4. Trigram fallback, branded and generic, only if tiers 1–3 return fewer
   than `limit`. It is capped and clearly last.

**`data_type` enters the final sort key.** The candidate-pool ordering
alone is not enough (1.2 cause 1).

**Locale.** Default to en-GB, since the users are UK-based (Q1).
"chips" → french fries and "biscuit" → cookies under en-GB. Under en-US,
the US meaning.

### 3.4 Building and reviewing the mapping

This follows the existing patterns: `ingredient_aliases.py` (closed
relationship vocabulary plus a schema test) and the phytate review CSV
workflow (row id, verdict, reviewer, date, notes).

- **Rules propose, a human file decides.**
  - A read-only script proposes candidates for each concept:
    - token rules on FDC names;
    - the preparation classifier;
    - SR/Foundation anchors;
    - seeds from the 124 existing `ingredient_aliases.py` UK entries.
  - It writes a CSV of proposals to the scratch area. Nothing is loaded
    from proposals.
- **Tracked file:** `backend/app/canonical_foods/canonical_foods_en_gb.csv`.
  - Columns: `concept, canonical_key, preparation_state, display_name_en_gb,
    display_name_en_us, anchor_fdc_id, alias, alias_locale, relationship,
    reviewer, review_date, notes`.
  - It contains only FDC identifiers and names plus hand-written terms.
    That is public-domain-sourced or our own text, with **no PhyFoodComp
    content**.
- **Validation in CI (SQLite, no catalogue):**
  - closed vocabularies;
  - no duplicate `(locale, alias)` pointing at different concepts unless
    marked ambiguous;
  - every row has a reviewer and date;
  - no alias equals another concept's key.
- **Validation at load time (Postgres):**
  - every `anchor_fdc_id` exists;
  - the anchor's classified preparation state equals the row's state;
  - the load fails as a whole and loads nothing on any error.
- **Corrections** are an edit to the CSV, reviewed in a PR, then reloaded.
  The loader is idempotent and replaces canonical rows by key, so a
  wrong mapping is fixed by changing one line. Existing diary entries made
  through a wrong mapping keep their concrete food. Nothing is rewritten
  retroactively, which matches snapshot semantics.

### 3.5 Migration and deploy

- **The migration only creates the four `canonical_*` tables**, plus
  indexes on `canonical_alias(lower(alias))` and
  `canonical_member(food_id)`.
  - `downgrade()` drops them.
  - No existing table or column is altered, and `foods` is not written,
    so the catalogue checksum is unchanged.
- **Data load:** a separate idempotent command, `python -m
  app.load_canonical_foods [--dry-run]`.
  - Production can only run commands in the deploy wrapper's fixed
    allowlist, so this needs either a new wrapper entry and a wrapper
    reinstall, or loading inside an alembic data migration. Q5 asks which.
  - Either way, the rehearse-migration job restores the production dump
    and runs `alembic upgrade head`. A data migration would be
    rehearsed against real data before the approval gate.
- **Every PR below touches `backend/`.** That triggers CI → the
  production-gated deploy, with rehearsal for migration PRs and the
  ordering guard from #122.
  - Approve each PR's deploy before merging the next, so that runs do
    not queue out of order.
  - Separately, the old pending run `45848826407` (0a1cb1b) should be
    rejected, as noted on 2026-11-27.
- **Rollback:**
  - PRs 1–3 have no schema, so roll back with `deploy.yml` dispatch plus
    `allow_rollback=true`.
  - PR 4 adds tables that the older code simply ignores, so a code
    rollback is safe without a downgrade.

### 3.6 Test plan

1. **Golden search tests in CI (SQLite).**
   - Fixture: a mini catalogue of about 250 rows.
     - Real FDC generic names for every query in 1.2.
     - Adversarial branded rows copied from the observed failures:
       "Artforum Internat'L. Magazine EGGPLANT DIP", "Rocket Science
       Games, Inc. BBQ SAUCE", "Wasabrod Ab Sweden SANDWICH", "HOUSE
       KOMBUCHA KOMBUCHA", "Double Cream French Brie", "SUGAR COOKIES,
       SUGAR", five versions of one branded product.
   - Golden file `tests/fixtures/search_golden_en_gb.json`, per query:
     - the expected top-1 `fdc_id`, or an allowed set;
     - `must_not_appear_in_top_5` patterns;
     - the expected preparation state when the query names one.
   - All 34 queries from 1.2.
   - The table in this document is the "before" baseline. The test asserts
     the "after".
2. **Full-catalogue golden report (not CI).**
   - `scripts/search_golden_report.py`, read-only, runs the same queries
     against a real catalogue and prints the 1.2 table plus timings.
   - It can run locally against Docker. Optionally it could run as a
     non-blocking step in the rehearse-migration job, which already
     restores the production dump (Q6).
3. **Invariant tests:**
   - no canonical member's state differs from its canonical's;
   - `select_phytate_observations` results for a fixture diary entry are
     identical before and after canonical tables are loaded;
   - no canonical table or endpoint exposes `compound_observations`
     fields, enforced by extending the existing
     `test_source_licence_policy_boundary` scan to the new modules;
   - the catalogue checksum is unchanged after load.
4. **Barcode tests:**
   - 12-, 13- and 14-digit and leading-zero equivalence;
   - collision rule (exact width first, then lowest-padding equivalent,
     then newest `fdc_id`);
   - non-digit input → 404, unchanged;
   - an existing exact hit is unchanged.
5. **Regression:**
   - existing `test_search.py` (28), `test_ingredient_aliases_schema.py`,
     and stock-recipe matching tests;
   - stock-recipe robustness, because changed ranking changes future recipe
     matches. Report diffs, don't silently re-match existing recipes.
6. **Performance:** the golden report records p50 and max latency. The
   target is no query above 1 s on the full catalogue. Today's max is
   8.3 s.

## 4. PR sequence (each independently shippable)

| PR | Scope | Schema? | Value on its own |
|---|---|---|---|
| **1** | **Search ranking and en-GB synonyms.** <ul><li>`data_type` and prep tie-break in the final sort</li><li>token-AND matching</li><li>similarity to the matched term</li><li>collapse branded versions in results</li><li>en-GB locale synonyms (rocket, swede, crisps, chips, biscuit, creams, sugars, flours, semi-skimmed, wholemeal, mince, houmous, tinned, rapeseed, porridge oats)</li></ul> Plus the golden SQLite tests and the read-only golden report script. | No | Fixes most ✗ rows in 1.2 for every user immediately. |
| 2 | **Barcode normalisation and miss UX.** <ul><li>GTIN-8/12/13/14 equivalence with a deterministic collision rule</li><li>on a miss, the diary opens name search with a hint ("Not in our database. Most products are US-listed. Search by name instead.")</li></ul> | No | Rows 7–12 of the hand-test list start working. Misses stop being a dead end. |
| 3 | **Preparation-state classifier** as a pure function over FDC names, with tests and a coverage report. Shown as a badge in search results. Used in PR 1's tie-break if PR 1 lands first with a simple version. | No | Users see "dry" vs "canned" before logging. Prerequisite for PR 4's invariant. |
| 4 | **Canonical tables, reviewed CSV, loader and validation.** Search tier 1 reads canonical aliases. Initial file: the 30 queries plus the 124 recipe-alias UK entries, anchors only (no typical values). | Additive | One curated answer per concept, with variants and provenance text. |
| 5 | **Typical values** (medoid logging, median display, refusal rules from 3.2) for canonicals without an anchor. | Additive table from PR 4 | Covers UK-only concepts with no SR/Foundation row. |
| 6 | Optional. **Golden report in the rehearse job** (non-blocking), and the Foundation energy/folate mapping fix (1.3) as its own PR. | No | Ongoing regression visibility on real data. Better Foundation anchors. |

**PR 5 is deferred** (Q4, answered 2026-11-28). In its place: **protein-free
SR staples.** `ingest_fdc.py` skips every row with no protein, so the
catalogue had no white sugar, cooking oil, salt, vinegar, plain tea or
water. A data migration inserts an owner-approved shortlist of 23 SR Legacy
rows with their FDC ids (`backend/app/fdc_staples.py`), and canonical rows
anchor on them. It changes the catalogue checksum (see 1.5).

Not proposed here: re-pointing existing GTINs to the newest label version
(a data change to `foods`, which alters the checksum) and new data sources
(Q7).

## 5. Risks

- **UK/US composition differences.** A regional alias can imply a false
  equivalence:
  - double cream (~48% fat) vs heavy (~36%);
  - semi-skimmed (~1.7%) vs US 2%;
  - UK flour and bread fortification differs from US enrichment.
  - **Mitigation:** the `relationship` field plus user-visible notes.
    These are `close_analogue`, not `exact`.
- **Mapping errors scale.** One wrong canonical affects every user.
  - **Mitigation:** human-reviewed file, CI and load validation, golden
    tests, easy single-line correction.
- **Preparation mis-classification** could still merge states.
  - **Mitigation:** an unknown state excludes the row, and the invariant
    is tested.
- **Ranking changes affect stock-recipe matching**
  (`food_matching.py` calls `search_foods_by_name`).
  - **Mitigation:** run the stock-recipe robustness report before and
    after PR 1, and review the diffs.
- **Locale ambiguity.** "chips" and "biscuit" will be wrong for any
  en-US user until locale is known.
- **Local copy is not production.** Counts may differ slightly. Re-run
  Appendix A on production before relying on exact figures.
- **Licence:** the main risk is accidental seeding from untracked
  PhyFoodComp review files.
  - **Mitigation:** an explicit rule in 3.4 and the boundary test
    extension in 3.6.

## 6. Open questions for you

1. **Locale source.** Should we hard-default to en-GB for everyone for
   now, or add a profile setting? Do any en-US users exist?
2. **Default preparation per concept for UK users.** Is "chickpeas" →
   tinned/drained, "lentils" → dry, "kidney beans" → tinned? I'd like your
   list for the initial 30.
3. **Semi-skimmed mapping.** US 2% (closer fat) or 1%, labelled
   `close_analogue`?
4. **Typical-value thresholds.** Are N ≥ 10 distinct products and an
   IQR/median of 0.5 or less acceptable? Or should we skip typical values
   entirely until UK data exists?
   - **Answered 2026-11-28: skip PR 5 for now.** On the full local
     catalogue the draft rule qualified only six UK concepts with no SR or
     Foundation row (halloumi, muesli, scones, flapjack, gnocchi, tikka
     masala sauce), and their micronutrients would show "not reported".
     The protein-free SR staples gap (sugar, oils, salt) went next instead.
   - If PR 5 is revisited, branded members are reviewed as **a name rule
     plus a tracked snapshot of the matched members** (fdc_id and name),
     reviewed in the PR. The load uses only the snapshot.
5. **Loading in production.** A new wrapper command (needs a wrapper
   reinstall), or an alembic data migration (rehearsed, but every CSV edit
   becomes a migration)?
6. **Golden report in the rehearse job.** OK to run read-only search
   queries against the restored dump there?
7. **UK data sources.** Is a separate licence review of CoFID and/or Open
   Food Facts wanted? That is out of scope here, and the repo has no
   records for either.
8. **FDC licence record.** The repo only has an informal "public domain"
   note. Do you want a formal FDC provenance record in docs? It would not
   go in `source_licence_policy.py`.
9. **Foundation energy and folate gaps** (31% and 0%). Should fixing the
   ingest nutrient mapping be its own PR before Foundation rows become
   canonical anchors?
10. **Barcode version.** Should a barcode keep returning the oldest label
    version (today), or should we plan a re-point to the newest? The
    re-point changes `foods` and the catalogue checksum.

## Appendix A: read-only census SQL

Run in a read-only session, `SET default_transaction_read_only = on;`.

```sql
-- data types and barcode coverage
SELECT data_type, count(*), count(gtin_upc) FROM foods GROUP BY 1 ORDER BY 2 DESC;

-- branded version duplication
SELECT count(*), count(DISTINCT lower(name)), count(DISTINCT gtin_upc)
FROM foods WHERE data_type = 'branded_food';

-- nutrient completeness
WITH t AS (SELECT coalesce(data_type,'(null)') dt, count(*) n FROM foods GROUP BY 1),
k AS (SELECT coalesce(f.data_type,'(null)') dt, fn.nutrient_key k, count(*) c
      FROM food_nutrients fn JOIN foods f ON f.id = fn.food_id
      WHERE fn.nutrient_key IN ('energy','protein','fiber_total','iron','zinc','calcium',
                                'magnesium','vitamin_b12','folate','vitamin_d')
      GROUP BY 1,2)
SELECT k.dt, t.n, k.k, k.c, round(100.0*k.c/t.n,1) FROM k JOIN t USING (dt) ORDER BY 1,3;

-- barcode widths and UK prefixes
SELECT length(gtin_upc), count(*) FROM foods WHERE gtin_upc IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;
SELECT count(*) FROM foods WHERE gtin_upc ~ '^50[0-9]{11}$';
SELECT count(*) FROM foods WHERE gtin_upc ~ '^0[0-9]{13}$';
```

The search table in 1.2 came from calling
`app.search.search_foods_by_name(db, q, limit=15)` in a session whose
transactions began with `SET TRANSACTION READ ONLY`.
