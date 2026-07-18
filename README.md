# Nutri-Matic

> *"Share and enjoy."*

## Problem

Calorie counters tell you how much energy is in your food. They don't tell you whether the
protein you ate can actually be used to build muscle, whether today's iron will be absorbed, or
whether two foods on your plate happen to cover each other's amino acid weaknesses. A
2,000-calorie day of white bread and a 2,000-calorie day of eggs, oily fish, and vegetables are
treated identically by a calorie counter. They are not remotely the same day — and if all you're
tracking is a number that treats them as equal, you have no way to know that.

## Solution

Nutri-Matic answers the question calorie counters skip: **is this food, meal, or day actually
good for you** — not just how much of it there is. Four things it computes that a calorie count
can't tell you:

- **Protein quality**, not just protein grams. 20g of protein from a food missing lysine isn't
  interchangeable with 20g from a food with a complete amino acid profile — your body can only use
  as much of each amino acid as the *most limited* one supplies. DIAAS and PDCAAS (the WHO/FAO
  standards for this) capture that; a gram count doesn't.
- **Micronutrient sufficiency**, not just presence. Logging a food that "contains iron" is
  meaningless without knowing how much, against how much you actually need — which itself depends
  on your sex, pregnancy/lactation status, and life stage, not a single generic figure.
- **Bioavailability**, not just nutrient amount. The iron in spinach and the iron in steak are
  chemically similar but absorbed at wildly different rates, and that rate itself depends on what
  else is on your plate (vitamin C helps, some inhibitors hurt). A nutrient total that ignores this
  overstates what your body actually gets — see the real example below.
- **Complementarity**, not just single foods in isolation. One food's amino acid weakness can be
  another's strength. Nutri-Matic computes this directly by actually simulating combined meals and
  scoring them, rather than reciting a folk-wisdom pairing list — see the real example below, which
  includes a case where the algorithm's answer isn't the one folklore would give.

Everything below is built to serve that goal, and every number the app shows is traceable back to
a real published source or an honestly-labelled estimate — see [Scientific methodology](#scientific-methodology)
and the in-app **Data & Methodology** page for the full trail.

## Example outputs

These are real numbers from the running app (USDA FoodData Central data, current build), not
illustrative placeholders — reproducible by hitting the same endpoints yourself.

**Protein quality isn't just "does it have protein."**
`GET /api/foods/1753/score?method=diaas` for *Rice, white, long-grain, regular, enriched, cooked*
returns a DIAAS of **63.9**, limited by **lysine** — meaning this food's usable protein value is
capped by its weakest amino acid, not its total protein grams. A gram count alone would never
surface that.

**Absorbed nutrients can be a fraction of logged nutrients.**
Logging 180g of raw spinach for dinner shows **4.88mg** of iron in the raw total — but the diary's
bioavailability estimate (Monsen model) puts **actually-absorbed** iron at **0.49mg**, about 10%,
because spinach's iron is entirely non-haem and non-haem iron absorbs far less efficiently than
haem iron even with vitamin C present to help. A raw nutrient total would silently overstate this
meal's real iron contribution by roughly 10x.

**Complementarity is computed, not recited.**
Asking Nutri-Matic what pairs well with that same lysine-limited rice
(`GET /api/foods/1753/complement?method=diaas`) doesn't return "beans" because folklore says so —
it actually simulates 100g-rice-plus-100g-candidate combinations against the whole food database
and ranks them by real, computed score improvement. In this case the top result is pork bratwurst
(rice's DIAAS jumps from 63.9 to over 200 combined), because a handful of processed meats happen
to be extremely lysine-dense per gram — a genuinely surprising answer a hardcoded "rice pairs with
beans" rule would never produce, and exactly the kind of honest-but-unglamorous result you get
when a system computes an answer instead of reporting a plausible-sounding one.

## Scientific methodology

Every number in the app traces back to one of these. The in-app **Data & Methodology** page
(linked in the nav, and via the ⓘ icons next to scores and nutrient values throughout the app)
covers this in full, including per-nutrient confidence notes and what's deliberately *not*
modelled — this section is the short version.

- **USDA FoodData Central** — Foundation Foods, SR Legacy, and Branded Foods CSV exports are the
  only food-composition data source. Nutrient amounts are USDA's own analytical/labelled values,
  not re-derived. Branded Foods is also what barcode scanning resolves against (`gtin_upc`).
- **FAO. 2013. *Dietary protein quality evaluation in human nutrition*** (Table 4.1) — the amino
  acid reference patterns DIAAS/PDCAAS scores are computed against.
- **Digestibility coefficients** — a small set of real published values (Kashyap et al. 2018,
  *Am J Clin Nutr* 108(5):980-987, for egg and chicken; the classic FAO 1991 *Protein Quality
  Evaluation* true-digestibility table for rice/corn/oats/peanuts/soybeans/legumes) where they
  exist, falling back to a broad food-category estimate otherwise — every score in the app is
  labelled `measured` or `estimated` so it's never ambiguous which you're looking at, including
  after aggregation into a recipe or a diary day (the combined figure is only `measured` if every
  contributing food's was).
- **UK Reference Nutrient Intake (RNI) → EFSA PRI/AI → US RDA/AI**, in that priority order, for
  vitamin/mineral/fibre daily reference values, with per-sex and pregnancy/lactation variants
  where a source specifies them, and a `live_confirmed` vs. `secondary_source` confidence tag per
  nutrient.
- **Monsen (1978/1982) iron bioavailability model** and **FAO (2004) Human Vitamin and Mineral
  Requirements** — the constants behind the diary's simplified per-meal iron absorption estimate
  (see the spinach example above).
- **ESPGHAN** calcium:phosphorus ratio guidance, for the diary's day-level Ca:P context.
- **Mifflin-St Jeor** BMR equation, for personalized daily energy targets. If your profile goal is
  set to weight loss (or visceral fat reduction, which uses the identical calculation), that target
  becomes a deficit — 15% below maintenance (10% for adults 65+, a smaller deficit given the higher
  risk of losing lean mass alongside fat), floored at 1,200/1,500 kcal (women/men) per commonly-cited
  NIH/NHLBI-style minimums, never applied during pregnancy/lactation. Always shown with a visible
  note, never silently applied — see the in-app methodology page's "Weight-loss calorie target"
  section for full sourcing.
- **`methodology_version`** — every score and DRV comparison the API returns is stamped with a
  version (see `backend/app/methodology.py`). Nutri-Matic recomputes everything live from current
  code and data rather than freezing historical results, so this stamp is how a change in
  methodology over time would actually be detected — it's what makes the transparency claims on
  this page auditable rather than aspirational.

Grocery prices are the one thing in the app that come from **you**, not a published source — the
budget feature multiplies out prices you enter yourself, never an external pricing API.

Known, deliberate gaps: phytates, oxalates, and tannins (real inhibitors of mineral absorption)
aren't modelled anywhere in the app, because USDA FoodData Central — the sole data source — doesn't
track them as nutrients at all. Rather than fabricate values, the app just doesn't claim to cover
them; see the in-app methodology page's "What this app doesn't do" section.

---

## Features

### Protein quality analysis
- **DIAAS** (Digestible Indispensable Amino Acid Score) — the WHO/FAO gold standard for protein quality, not capped at 100%
- **PDCAAS** fallback for foods without per-amino-acid digestibility data, capped at 100% per convention
- Full amino acid breakdown: all nine indispensable AAs (histidine, isoleucine, leucine, lysine, methionine+cysteine, phenylalanine+tyrosine, threonine, tryptophan, valine)
- Limiting amino acid identification per food, recipe, and diary day
- **Protein complementation engine** — given a food's limiting amino acid, simulates real pairings from the food database and ranks them by actual computed score improvement, not a heuristic guess

### Essential fats
- Omega-3 (ALA, EPA, DHA) and omega-6 (LA, arachidonic acid) tracking
- n-3:n-6 ratio
- Saturated / monounsaturated / polyunsaturated breakdown

### Dietary fibre
- Total, soluble, and insoluble fibre
- Prebiotic fibre types (resistant starch, inulin, beta-glucan) where data is available

### Micronutrients
- Fat-soluble vitamins: A (retinol + carotenoids), D, E, K1/K2
- Water-soluble vitamins: B1–B12, C, folate, choline
- Minerals: calcium, magnesium, iron (haem/non-haem), zinc, selenium, iodine, potassium, phosphorus, manganese, copper
- **Bioavailability estimate** — per-meal iron absorption (Monsen model constants + FAO enhancer thresholds) and day-level calcium:phosphorus context (ESPGHAN guidance), always labelled measured vs. estimated

### Meal and diet optimisation
- **Meal optimisation engine** — analyses a logged meal against your day's single worst nutrient gap and recommends real, simulated add/swap changes ranked by measured %DRV improvement (and improvement per 100kcal, where a change has a calorie cost)
- **Nutrient gap suggestions** — your day's single worst gap, with real foods ranked by how much of that nutrient they'd add

### Diet-level analysis
- Multi-day diary logging, with barcode scanning against USDA Branded Foods
- Nutrient gap identification vs. a full DRV matrix (UK RNI → EFSA PRI/AI → US RDA/AI), personalized by sex/pregnancy/lactation
- Diet trends over time (weekly/monthly), averaged only over days you actually logged
- Personalized daily energy target (Mifflin-St Jeor)
- Weight tracking over time, feeding back into the energy calculation
- Recipe builder with per-serving amino acid and micronutrient breakdown
- User profiles (age, sex, pregnancy/lactation, activity level)

### Planning and logging friction-reducers
- Weekly meal planning with a shopping list and a grocery budget estimate (prices you enter yourself)
- Recurring meal-plan templates (save a week, reapply it to any future week) and diary meal templates (save a single meal, reapply it any day)
- Recent/frequent quick-add, and one-click "copy this day" for the diary
- Recipe sharing, rating, comments, tagging, and collections
- Saved nutrient-goal search filters for foods and recipes
- Server-side food search with synonym/plural handling and typo-tolerant fuzzy matching

### Transparency
- Every food traceable through a real provenance chain: FDC ID → dataset → USDA nutrient number → stored value → any recipe/diary aggregation → DRV comparison, exposed via API and the in-app **Data & Methodology** page
- Every digestibility and DRV figure explicitly labelled by confidence tier — never a fabricated precision number, always a checkable fact about how it was sourced
- Every score and DRV comparison is stamped with a `methodology_version` (see [Scientific methodology](#scientific-methodology))
- Export/print (PDF and CSV) for diary days, trends, shopping lists, and recipes

### Installable
- PWA — installs to a home screen, works offline for the app shell (never caches live nutrition data)

---

## Installation

Backend + Postgres, via Docker:

```bash
docker-compose up -d --build
```

Frontend (separate, dev server):

```bash
cd frontend
npm install
npm run dev
```

### Food data (required — the app has zero foods until you do this)

Nothing is bundled or seeded automatically. `Base.metadata.create_all()` creates the empty
tables on first startup, but `foods`/`food_nutrients` stay empty until you explicitly ingest a
real USDA export — skip this and every search, recipe, and score endpoint just has nothing to
work with (no error, just empty results).

**1. Download a USDA FoodData Central export** from the
[FDC "Download Datasets" page](https://fdc.nal.usda.gov/download-datasets.html). Three datasets
exist; you don't need all three:

| Dataset | Zipped size | Rows ingested | Needed for |
|---|---|---|---|
| Foundation Foods | ~3MB | ~400 | Core whole foods with a full amino acid panel — start here |
| SR Legacy | ~6MB | ~7,500 | The bulk of generic/whole-food coverage (onions, chicken breast, rice, etc.) |
| Branded Foods | **several GB zipped**, ~2 million rows | most of it | Barcode scanning (`gtin_upc`) and packaged/branded products specifically |

Foundation + SR Legacy together take seconds to download and a few minutes to ingest — enough
for a fully working dev instance (recipes, scoring, search, diary) without touching Branded at
all. Only add Branded Foods if you need barcode scanning or branded-product search — budget real
time and disk for it (multi-GB download, tens of minutes to ingest, and a proportionally larger
`food_nutrients` table) and do it last.

**2. Ingest whichever datasets you downloaded** (each `--dir` points at one unzipped dataset
folder; pass as many as you want in one run):

```bash
cd backend
python -m app.ingest_fdc \
  --dir path/to/FoodData_Central_foundation_food_csv_2025-04-24 \
  --dir path/to/FoodData_Central_sr_legacy_food_csv_2018-04
```

Only foods with a usable protein value are kept (amino acid scoring needs it) — the command
prints a per-dataset summary (`considered`/`skipped_no_protein`/`inserted`) so you can see this
happened. Foods it skips for that reason (mainly pure fats/oils/sugars/salt) aren't a bug; see
the next step.

**3. Backfill digestibility coefficients** (DIAAS/PDCAAS scores are null for every food until
this runs — it's a separate step from ingestion on purpose, so the reference table in
`digestibility_reference.py` can be revised and re-applied without re-ingesting):

```bash
python -m app.assign_digestibility
```

**4. (Optional) Seed pure-fat foods** — oils/ghee have no protein, so step 2 always skips them
(by design: amino acid scoring needs a protein value, and fabricating one would misrepresent the
food). If you want recipes with realistic calorie counts for dishes that use oil/butter/ghee,
add a small set of hand-entered pure-fat foods (protein 0, so they never affect any DIAAS/PDCAAS
score):

```bash
python -m app.seed_manual_foods
```

**5. (Optional) Populate the curated stock recipe library** — a set of
recipes visible to every user, organised into collections, with computed
nutrition and robustness ratings:

```bash
python -m app.stock_recipes discover
python -m app.stock_recipes fetch
python -m app.stock_recipes parse
python -m app.stock_recipes match
python -m app.stock_recipes analyse
python -m app.stock_recipes review-export
# review .stock_recipe_cache/review.csv, then:
python -m app.stock_recipes import-approved
```

See [docs/stock-recipes.md](docs/stock-recipes.md) for what each stage
does, how sourcing/copyright boundaries work, and what the robustness
ratings mean.

### First-run checklist

After the steps above, confirm the app actually has data before assuming something's broken:

```bash
curl http://localhost:8000/api/foods/search-by-name?q=chicken
```

If that returns `[]`, the ingestion step above didn't run against the database the app is
actually pointed at — check `DATABASE_URL` (backend loads `backend/.env` automatically; there's
no default fallback to a specific port, so a mismatched port here is the most common cause) and
re-run step 2.

### Troubleshooting

- **Empty search results / "Food not found" everywhere, no errors in the logs** — almost always
  step 2 (ingestion) hasn't been run against the database the app is actually using. Check
  `DATABASE_URL` first, not the app code.
- **DIAAS/PDCAAS always show "no digestibility data" / null** — step 3 (`assign_digestibility`)
  hasn't been run yet, or hasn't been re-run since you last edited `digestibility_reference.py`.
  It's idempotent and safe to re-run any time.
- **`ALTER TABLE`/column-not-found errors on an existing database** — this project has no
  migration framework; `Base.metadata.create_all()` only creates tables that don't exist yet, it
  never alters existing ones. See [DEPLOYMENT.md](DEPLOYMENT.md)'s "Manual migrations" section for
  every `ALTER TABLE` needed to bring an existing database up to date with the current schema.
- **Postgres connection refused** — most commonly the Postgres service/container simply isn't
  running, or `DATABASE_URL`'s port doesn't match what Postgres is actually listening on
  (`docker-compose.yml`'s default and a locally-installed Postgres's default port frequently
  differ — check both rather than assuming).

Deploying beyond your own machine (real `JWT_SECRET`, CORS origins, etc.)? See
[DEPLOYMENT.md](DEPLOYMENT.md). Contributing code? See [CONTRIBUTING.md](CONTRIBUTING.md), which
also covers running the test suite and CI checks locally.

---

## Stack

- Python / FastAPI backend
- SvelteKit frontend
- PostgreSQL for food composition and user data

---

## Status

Actively developed. All core modules described above — protein quality, micronutrients,
bioavailability, diet-level analysis, meal optimisation, meal planning, and the
transparency/provenance layer — are built and tested (392 backend tests, run in CI against a real
Postgres instance on every push — see `.github/workflows/ci.yml`). Contributions and data
corrections welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Licence

MIT — see `LICENSE` for details.
