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

- USDA FoodData Central (foundational food composition)
- McCance and Widdowson's *The Composition of Foods* (UK-specific data)
- FAO/WHO DIAAS reference values and digestibility tables
- EFSA Dietary Reference Values

---

## Getting started

```bash
pip install -r requirements.txt
python app.py
```

Or with Docker:

```bash
docker-compose up
```

---

## Stack

- Python / FastAPI backend
- React frontend
- PostgreSQL for food composition data
- Redis for session caching

---

## Status

Early development. Protein/amino acid analysis (DIAAS/PDCAAS/TID) is the first module under active build. Contributions and data corrections welcome — see `CONTRIBUTING.md`.

---

## Licence

MIT — see `LICENSE` for details.
