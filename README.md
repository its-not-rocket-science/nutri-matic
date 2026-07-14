# Nutri-Matic

> *"Share and enjoy."*

A micronutrient analysis tool for food, recipes, and personal diets. Nutri-matic tells you not just what you're eating, but whether you're eating *well* — starting with protein quality via digestibility-corrected scoring (DIAAS/PDCAAS), and extending through essential fatty acids, dietary fibre, vitamins, and minerals.

Most nutrition apps count calories. Nutri-matic counts what actually matters.

---

## Features (current and planned)

### Protein quality analysis
- **DIAAS** (Digestible Indispensable Amino Acid Score) — the WHO/FAO gold standard for protein quality
- **PDCAAS** fallback for foods without full digestibility data
- **TID** (True Ileal Digestibility) where available
- Full amino acid breakdown: all nine essential AAs (histidine, isoleucine, leucine, lysine, methionine+cysteine, phenylalanine+tyrosine, threonine, tryptophan, valine)
- Limiting amino acid identification per food and per meal

### Essential fats
- Omega-3 (ALA, EPA, DHA) and omega-6 (LA, AA) tracking
- n-3:n-6 ratio
- Saturated / monounsaturated / polyunsaturated breakdown

### Dietary fibre
- Total, soluble, and insoluble fibre
- Prebiotic fibre types where data available

### Micronutrients
- Fat-soluble vitamins: A (retinol + carotenoids), D, E, K1/K2
- Water-soluble vitamins: B1–B12, C, folate, choline
- Minerals: calcium, magnesium, iron (haem/non-haem), zinc, selenium, iodine, potassium, phosphorus, manganese, copper
- Bioavailability adjustments (e.g., non-haem iron absorption, calcium–phosphorus competition)

### Diet-level analysis
- Multi-day diet logging
- Nutrient gap identification vs. DRVs (UK/EFSA reference values)
- Recipe builder with per-serving breakdown
- User profiles (age, sex, pregnancy/lactation, activity level)

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
  labelled `measured` or `estimated` so it's never ambiguous which you're looking at.
- **UK Reference Nutrient Intake (RNI) → EFSA PRI/AI → US RDA/AI**, in that priority order, for
  vitamin/mineral/fibre daily reference values, with per-sex and pregnancy/lactation variants
  where a source specifies them.
- **Monsen (1978/1982) iron bioavailability model** and **FAO (2004) Human Vitamin and Mineral
  Requirements** — the constants behind the diary's simplified per-meal iron absorption estimate.
- **ESPGHAN** calcium:phosphorus ratio guidance, for the diary's day-level Ca:P context.
- **Mifflin-St Jeor** BMR equation, for personalized daily energy targets.

Grocery prices are the one thing in the app that come from **you**, not a published source — the
budget feature multiplies out prices you enter yourself, never an external pricing API.

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

Early development. Protein/amino acid analysis (DIAAS/PDCAAS/TID) is the first module under active build. Contributions and data corrections welcome — see `CONTRIBUTING.md`.

---

## Licence

MIT — see `LICENSE` for details.
