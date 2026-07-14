# Nutri-Matic

> *"Share and enjoy."*

Most nutrition apps count calories. Nutri-Matic optimises nutritional quality.

Calories tell you how much energy is in your food. They don't tell you whether the protein you
ate can actually be used to build muscle, whether today's iron will be absorbed, or whether two
foods on your plate happen to cover each other's amino acid weaknesses. A 2,000-calorie day of
white bread and a 2,000-calorie day of eggs, oily fish, and vegetables are treated identically by
a calorie counter. They are not remotely the same day.

Nutri-Matic exists to answer the question calorie counters skip: **is this food, meal, or day
actually good for you** — not just how much of it there is.

- **Protein quality**, not just protein grams. 20g of protein from a food missing lysine isn't
  interchangeable with 20g from a food that has a complete amino acid profile — your body can only
  use as much of each amino acid as the *most limited* one supplies. DIAAS and PDCAAS (the WHO/FAO
  standards for this) capture that; a gram count doesn't.
- **Micronutrient sufficiency**, not just presence. Logging a food that "contains iron" is
  meaningless without knowing how much, against how much you actually need — which itself depends
  on your sex, pregnancy/lactation status, and life stage, not a single generic figure.
- **Bioavailability**, not just nutrient amount. The iron in spinach and the iron in steak are
  chemically similar but absorbed at wildly different rates, and that rate itself depends on what
  else is on your plate (vitamin C helps, some inhibitors hurt). A nutrient total that ignores this
  overstates what your body actually gets.
- **Complementarity**, not just single foods in isolation. Classic food pairings (beans and rice,
  for example) work because one food's amino acid weakness is another's strength. Nutri-Matic
  computes this directly — real before/after protein-quality scores for a suggested pairing, not a
  folk-wisdom list.

Everything below is built to serve that goal, and every number the app shows is traceable back to
a real published source or an honestly-labelled estimate — see [Data sources](#data-sources) and
the in-app **Data & Methodology** page for the full trail.

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

### Diet-level analysis
- Multi-day diary logging, with barcode scanning against USDA Branded Foods
- Nutrient gap identification vs. a full DRV matrix (UK RNI → EFSA PRI/AI → US RDA/AI), personalized by sex/pregnancy/lactation
- **Nutrient gap suggestions** — your day's single worst gap, with real foods ranked by how much of that nutrient they'd add
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

### Transparency
- Every food traceable through a real provenance chain: FDC ID → dataset → USDA nutrient number → stored value → any recipe/diary aggregation → DRV comparison, exposed via API and the in-app **Data & Methodology** page
- Every digestibility and DRV figure explicitly labelled by confidence tier — never a fabricated precision number, always a checkable fact about how it was sourced
- Every score and DRV comparison is stamped with a `methodology_version` — Nutri-Matic recomputes everything live from current code and data (a diary day always reflects *today's* methodology, not the methodology of the day it was logged), so this version stamp is how you'd detect a methodology change over time rather than a frozen historical snapshot; see `backend/app/methodology.py`
- Export/print (PDF and CSV) for diary days, trends, shopping lists, and recipes

### Installable
- PWA — installs to a home screen, works offline for the app shell (never caches live nutrition data)

---

## Data sources

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
  Requirements** — the constants behind the diary's simplified per-meal iron absorption estimate.
- **ESPGHAN** calcium:phosphorus ratio guidance, for the diary's day-level Ca:P context.
- **Mifflin-St Jeor** BMR equation, for personalized daily energy targets.

Grocery prices are the one thing in the app that come from **you**, not a published source — the
budget feature multiplies out prices you enter yourself, never an external pricing API.

Known, deliberate gaps: phytates, oxalates, and tannins (real inhibitors of mineral absorption)
aren't modelled anywhere in the app, because USDA FoodData Central — the sole data source — doesn't
track them as nutrients at all. Rather than fabricate values, the app just doesn't claim to cover
them; see the in-app methodology page's "What this app doesn't do" section.

---

## Getting started

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

Food data isn't bundled — ingest a USDA FoodData Central export yourself:

```bash
cd backend
python -m app.ingest_fdc --dir path/to/FoodData_Central_foundation_food_csv_...
```

---

## Stack

- Python / FastAPI backend
- SvelteKit frontend
- PostgreSQL for food composition and user data

---

## Status

Actively developed. All core modules described above — protein quality, micronutrients,
bioavailability, diet-level analysis, meal planning, and the transparency/provenance layer — are
built and tested. Contributions and data corrections welcome — see `CONTRIBUTING.md`.

---

## Licence

MIT — see `LICENSE` for details.
